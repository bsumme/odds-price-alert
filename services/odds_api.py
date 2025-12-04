"""The Odds API client wrapper."""

import json
import logging
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests
from fastapi import HTTPException

BASE_URL = "https://api.the-odds-api.com/v4"

logger = logging.getLogger("uvicorn.error")


def get_api_key() -> str:
    """Get The Odds API key from environment variable."""
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing THE_ODDS_API_KEY environment variable. "
            "Set it in Windows Environment Variables and restart."
        )
    return api_key


def _log_real_api_response(
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    payload: List[Dict[str, Any]],
    endpoint: str = "odds",
) -> None:
    """
    Append the real API response to a local text file so it can be
    compared to dummy data later. Failures here should never break
    the main request flow.
    """
    try:
        # Store under project_root/logs so it's easy to find.
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        log_path = os.path.join(logs_dir, "real_odds_api_responses.jsonl")

        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sport_key": sport_key,
            "regions": regions,
            "markets": markets,
            "bookmaker_keys": bookmaker_keys,
            "endpoint": endpoint,
            "response": payload,
        }

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record))
            f.write("\n")
    except Exception:
        # Silent failure – logging should not impact live behavior.
        pass


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
    dummy_data_generator=None,
) -> List[Dict[str, Any]]:
    """
    Core call to /v4/sports/{sport_key}/odds.
    If use_dummy_data is True, uses dummy_data_generator if provided.
    """
    if use_dummy_data and dummy_data_generator:
        return dummy_data_generator(sport_key, markets, bookmaker_keys)

    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    response = requests.get(url, params=params, timeout=15)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {response.status_code}, {response.text}",
        )

    data: List[Dict[str, Any]] = response.json()

    # Persist real API output to a text file for later comparison to dummy data.
    _log_real_api_response(
        sport_key=sport_key,
        regions=regions,
        markets=markets,
        bookmaker_keys=bookmaker_keys,
        payload=data,
    )

    return data


def fetch_sport_events(api_key: str, sport_key: str) -> List[Dict[str, Any]]:
    """Fetch the list of events for a sport using The Odds API."""

    events_url = f"{BASE_URL}/sports/{sport_key}/events"
    logger.info("Fetching events list: url=%s", events_url)

    response = requests.get(events_url, params={"apiKey": api_key}, timeout=15)
    if response.status_code != 200:
        logger.error(
            "Events API error: status=%s body=%s", response.status_code, response.text
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Error fetching events from The Odds API: "
                f"{response.status_code}, {response.text}"
            ),
        )

    return response.json()


def _parse_invalid_markets(error_text: str) -> List[str]:
    """Extract the rejected market keys from a 422 error payload."""

    try:
        parsed = json.loads(error_text)
        message = parsed.get("message", "") if isinstance(parsed, dict) else ""
    except Exception:
        message = ""

    if not message:
        message = error_text or ""

    match = re.search(r"Invalid markets:\s*([^\"]+)", message)
    if not match:
        return []

    markets_raw = match.group(1)
    return [m.strip() for m in markets_raw.split(",") if m.strip()]


def fetch_player_props(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    team: Optional[str] = None,
    event_id: Optional[str] = None,
    use_dummy_data: bool = False,
    dummy_data_generator=None,
) -> List[Dict[str, Any]]:
    """
    Retrieve player prop markets by first fetching events, then requesting event odds.

    The Odds API serves player props through the event odds endpoint rather than a
    dedicated player props route. We fetch the list of events for the sport, optionally
    filter by team, and then request odds for each event with the desired player prop
    markets enabled.
    """
    if use_dummy_data and dummy_data_generator:
        return dummy_data_generator(sport_key, markets, bookmaker_keys)

    events_url = f"{BASE_URL}/sports/{sport_key}/events"
    logger.info("Fetching events for player props: url=%s", events_url)
    events_response = requests.get(events_url, params={"apiKey": api_key}, timeout=15)
    if events_response.status_code != 200:
        logger.error(
            "Player props events API error: status=%s body=%s",
            events_response.status_code,
            events_response.text,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Error fetching events from The Odds API: "
                f"{events_response.status_code}, {events_response.text}"
            ),
        )

    events: List[Dict[str, Any]] = events_response.json()
    if team:
        team_lower = team.lower()

        def _matches_team(event_team: str) -> bool:
            name = event_team.lower()
            return team_lower in name or name in team_lower

        before_team_filter = len(events)
        events = [
            e
            for e in events
            if _matches_team(e.get("home_team", ""))
            or _matches_team(e.get("away_team", ""))
        ]
        logger.info(
            "Filtered events by team '%s': %d -> %d", team, before_team_filter, len(events)
        )

    if not events:
        logger.info("No events found for sport=%s after filtering; returning empty list", sport_key)
        return []

    if event_id:
        events = [e for e in events if e.get("id") == event_id]
        logger.info(
            "Filtered events by event_id '%s': %d remaining", event_id, len(events)
        )

        if not events:
            return []

    requested_markets: List[str] = [m.strip() for m in markets.split(",") if m.strip()]

    odds_params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    def _fetch_player_props_via_odds_endpoint(markets_param: str) -> List[Dict[str, Any]]:
        """
        Fallback to the sport odds endpoint when the event odds endpoint rejects
        player prop markets (e.g., returns INVALID_MARKET 422 errors).
        """
        logger.warning(
            "Falling back to /odds endpoint for player props: sport=%s markets=%s",
            sport_key,
            markets_param,
        )
        try:
            fallback_events = fetch_odds(
                api_key=api_key,
                sport_key=sport_key,
                regions=regions,
                markets=markets_param,
                bookmaker_keys=bookmaker_keys,
                use_dummy_data=False,
            )
        except HTTPException as exc:
            logger.error(
                "Fallback /odds call for player props failed: status=%s detail=%s",
                exc.status_code,
                exc.detail,
            )
            return []

        # If the caller filtered events by team, respect that here as well.
        if team:
            allowed_event_ids = {e.get("id") for e in events if e.get("id")}
            fallback_events = [
                e for e in fallback_events if e.get("id") in allowed_event_ids
            ]

        _log_real_api_response(
            sport_key=sport_key,
            regions=regions,
            markets=markets_param,
            bookmaker_keys=bookmaker_keys,
            payload=fallback_events,
            endpoint="odds_player_props_fallback",
        )

        return fallback_events

    collected_events: List[Dict[str, Any]] = []
    active_markets: List[str] = list(requested_markets)

    for event in events:
        event_id = event.get("id")
        if not event_id:
            logger.warning("Skipping event without id: %s", event)
            continue

        event_url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        odds_params["markets"] = ",".join(active_markets)

        logger.info(
            "Calling event odds for player props: url=%s event_id=%s regions=%s markets=%s bookmakers=%s",
            event_url,
            event_id,
            regions,
            odds_params["markets"],
            bookmaker_keys,
        )
        response = requests.get(event_url, params=odds_params, timeout=15)

        if response.status_code == 422:
            invalid_markets = _parse_invalid_markets(response.text)
            if invalid_markets:
                active_markets = [m for m in active_markets if m not in invalid_markets]
                logger.warning(
                    "Retrying player props for event %s without invalid markets: %s",
                    event_id,
                    ",".join(sorted(invalid_markets)),
                )

                if not active_markets:
                    logger.error(
                        "All requested player prop markets were rejected for event %s; skipping",
                        event_id,
                    )
                    continue

                odds_params["markets"] = ",".join(active_markets)
                response = requests.get(event_url, params=odds_params, timeout=15)

            if response.status_code == 422 and "Invalid markets" in response.text:
                return _fetch_player_props_via_odds_endpoint(odds_params["markets"])

        logger.info(
            "Event odds API response for player props (event_id=%s): status=%s body=%s",
            event_id,
            response.status_code,
            response.text,
        )

        if response.status_code != 200:
            logger.error(
                "Event odds API error for player props: status=%s body=%s",
                response.status_code,
                response.text,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Error from The Odds API when fetching player props: "
                    f"{response.status_code}, {response.text}"
                ),
            )

        event_data = response.json()
        if isinstance(event_data, list):
            collected_events.extend(event_data)
        else:
            collected_events.append(event_data)

    logger.info(
        "Player props API returned %d events for sport=%s market=%s",
        len(collected_events),
        sport_key,
        odds_params.get("markets", markets),
    )

    _log_real_api_response(
        sport_key=sport_key,
        regions=regions,
        markets=odds_params.get("markets", markets),
        bookmaker_keys=bookmaker_keys,
        payload=collected_events,
        endpoint="event_player_props",
    )

    return collected_events






