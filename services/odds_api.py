"""The Odds API client wrapper."""

import json
import logging
import os
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


def fetch_player_props(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    team: Optional[str] = None,
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
            team_name = event_team.lower()
            return team_lower in team_name or team_name in team_lower

        events = [
            e
            for e in events
            if _matches_team(e.get("home_team", ""))
            or _matches_team(e.get("away_team", ""))
        ]
        logger.info("Filtered events by team '%s': %d remaining", team, len(events))

    if not events:
        logger.info("No events found for sport=%s after filtering; returning empty list", sport_key)
        return []

    odds_params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    collected_events: List[Dict[str, Any]] = []
    for event in events:
        event_id = event.get("id")
        if not event_id:
            logger.warning("Skipping event without id: %s", event)
            continue

        event_url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        logger.info(
            "Calling event odds for player props: url=%s event_id=%s regions=%s markets=%s bookmakers=%s",
            event_url,
            event_id,
            regions,
            markets,
            bookmaker_keys,
        )
        response = requests.get(event_url, params=odds_params, timeout=15)
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
        markets,
    )

    _log_real_api_response(
        sport_key=sport_key,
        regions=regions,
        markets=markets,
        bookmaker_keys=bookmaker_keys,
        payload=collected_events,
        endpoint="event_player_props",
    )

    return collected_events






