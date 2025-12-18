"""The Odds API client wrapper."""

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import HTTPException

try:  # pragma: no cover - exercised in tests via fallback
    import aiohttp
except ImportError:  # pragma: no cover - fallback when aiohttp is unavailable
    aiohttp = None

from utils.logging_control import (
    TraceLevel,
    get_trace_level_from_env,
    should_log_api_calls,
    should_log_trace_entries,
    truncate_for_log,
)
from services.odds_cache import cached_odds

BASE_URL = "https://api.the-odds-api.com/v4"

logger = logging.getLogger("uvicorn.error")
TRACE_LEVEL = get_trace_level_from_env()
EVENT_ODDS_CONCURRENCY_LIMIT = 5
RATE_LIMIT_MAX_ATTEMPTS = 3


class ApiCreditTracker:
    """Track SpotOddsAPI/The Odds API credit usage from response headers."""

    def __init__(self) -> None:
        self.first_header_used: Optional[int] = None
        self.last_header_used: Optional[int] = None
        self.header_usage: int = 0
        self.request_count: int = 0

    def record_response(self, response: Any) -> None:
        """Update usage counters from an API response."""

        self.request_count += 1
        headers = getattr(response, "headers", {}) or {}
        raw_used = headers.get("x-requests-used")
        if raw_used is None:
            return

        try:
            used_val = int(raw_used)
        except (TypeError, ValueError):
            return

        if self.first_header_used is None:
            self.first_header_used = used_val
            self.last_header_used = used_val
            return

        if self.last_header_used is None:
            self.last_header_used = used_val
            return

        if used_val >= self.last_header_used:
            self.header_usage += used_val - self.last_header_used
        self.last_header_used = used_val

    @property
    def total_credits_used(self) -> int:
        """Return the best-effort credit usage total for this tracker."""

        header_total = 0
        if self.first_header_used is not None and self.last_header_used is not None:
            header_total = max(
                self.header_usage, self.last_header_used - self.first_header_used
            )

        # Fall back to counting requests if headers are unavailable
        return header_total or self.request_count


def _record_credit_usage(
    response: Any, credit_tracker: Optional[ApiCreditTracker]
) -> None:
    if credit_tracker is None:
        return

    try:
        credit_tracker.record_response(response)
    except Exception:
        # Never let credit tracking interfere with the primary workflow
        logger.debug("Failed to record credit usage", exc_info=True)


def _log_api_request(endpoint: str, url: str, params: Dict[str, Any]) -> None:
    """Log outgoing API request details in debug mode."""

    if not should_log_api_calls(TRACE_LEVEL):
        return

    logger.debug("Calling %s endpoint: url=%s params=%s", endpoint, url, params)


def _log_api_response(endpoint: str, response: Any) -> None:
    """Log API response details in debug mode."""

    if not should_log_api_calls(TRACE_LEVEL):
        return

    truncated_body = truncate_for_log(response.text)
    logger.debug(
        "%s response status=%s body=%s", endpoint, response.status_code, truncated_body
    )


def _format_outcome_for_human_log(outcome: Dict[str, Any]) -> Optional[str]:
    """Return a concise description of a single outcome for human-readable logs."""

    name = outcome.get("name")
    price = outcome.get("price")
    point = outcome.get("point")

    if name is None and price is None and point is None:
        return None

    components = [str(name)] if name is not None else ["Outcome"]

    if point is not None:
        components.append(str(point))
    if price is not None:
        components.append(f"at {price}")

    return " ".join(components)


def _extract_participant_name(outcomes: List[Dict[str, Any]]) -> Optional[str]:
    """Return the first player/participant name found in the provided outcomes."""

    for outcome in outcomes:
        for field in ("description", "participant", "player_name"):
            candidate = outcome.get(field)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()

    return None


def build_human_readable_logs(
    *,
    payload: List[Dict[str, Any]],
    markets: str,
    bookmaker_keys: List[str],
) -> List[str]:
    """Construct abbreviated, human-friendly log lines for odds responses."""

    market_list = [m.strip() for m in markets.split(",") if m.strip()]
    messages: List[str] = []

    for event in payload:
        home = event.get("home_team") or "Home"
        away = event.get("away_team") or "Away"
        bookmakers = event.get("bookmakers", []) or []

        for market_key in market_list:
            book_names: List[str] = []
            summaries: List[str] = []
            participant_name: Optional[str] = None

            for bookmaker in bookmakers:
                book_key = bookmaker.get("key")
                if book_key and bookmaker_keys and book_key not in bookmaker_keys:
                    continue

                market = next(
                    (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                    None,
                )
                if not market:
                    continue

                outcomes = market.get("outcomes", []) or []
                prioritized = [
                    outcome
                    for outcome in outcomes
                    if outcome.get("name") in {home, away}
                ]
                selected = prioritized if prioritized else outcomes

                if participant_name is None and selected:
                    participant_name = _extract_participant_name(selected)

                formatted_outcomes = [
                    summary
                    for summary in (
                        _format_outcome_for_human_log(outcome)
                        for outcome in selected[:2]
                    )
                    if summary
                ]

                if not formatted_outcomes:
                    continue

                book_label = bookmaker.get("title") or bookmaker.get("key") or "Bookmaker"
                book_names.append(book_label)
                summaries.append(
                    f"{book_label} has {' / '.join(formatted_outcomes)}"
                )

            if not summaries:
                continue

            matchup = f"{away} vs {home}"
            books_phrase = " and ".join(book_names)
            messages.append(
                f"Retrieved {matchup} for market {market_key} at {books_phrase}"
            )

            summary_message = " | ".join(summaries)
            if participant_name:
                summary_message = f"{participant_name} {summary_message}"

            messages.append(summary_message)

    return messages


def _log_human_readable_response(
    *,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    payload: List[Dict[str, Any]],
    endpoint: str,
) -> None:
    """Emit human-readable summaries instead of raw JSON payloads."""

    messages = build_human_readable_logs(
        payload=payload,
        markets=markets,
        bookmaker_keys=bookmaker_keys,
    )

    prefix = f"HumanReadable log for {endpoint} sport={sport_key} regions={regions}"
    if not messages:
        logger.info("%s: no bookmakers with prices to summarize", prefix)
        return

    logger.info(prefix)
    for message in messages:
        logger.info(message)


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
    if TRACE_LEVEL == TraceLevel.HUMAN:
        _log_human_readable_response(
            sport_key=sport_key,
            regions=regions,
            markets=markets,
            bookmaker_keys=bookmaker_keys,
            payload=payload,
            endpoint=endpoint,
        )
        return

    if not should_log_trace_entries(TRACE_LEVEL):
        return

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


@cached_odds(ttl=5)
def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
    dummy_data_generator=None,
    credit_tracker: Optional[ApiCreditTracker] = None,
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
    _log_api_request("odds", url, params)
    response = requests.get(url, params=params, timeout=15)
    _log_api_response("odds", response)
    _record_credit_usage(response, credit_tracker)
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


@cached_odds(ttl=300)
def fetch_sport_events(
    api_key: str, sport_key: str, credit_tracker: Optional[ApiCreditTracker] = None
) -> List[Dict[str, Any]]:
    """Fetch the list of events for a sport using The Odds API."""

    events_url = f"{BASE_URL}/sports/{sport_key}/events"
    logger.info("Fetching events list: url=%s", events_url)
    _log_api_request("events", events_url, {"apiKey": api_key})

    response = requests.get(events_url, params={"apiKey": api_key}, timeout=15)
    _log_api_response("events", response)
    _record_credit_usage(response, credit_tracker)
    if response.status_code != 200:
        logger.error(
            "Events API error: status=%s body=%s",
            response.status_code,
            truncate_for_log(response.text),
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Error fetching events from The Odds API: "
                f"{response.status_code}, {response.text}"
            ),
        )

    return response.json()


def _parse_datetime(timestamp: Optional[str]) -> Optional[datetime]:
    """Parse ISO timestamps that may include trailing Z into aware datetimes."""

    if not timestamp:
        return None

    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _filter_events_within_hours(
    events: List[Dict[str, Any]], hours: int = 48
) -> List[Dict[str, Any]]:
    """Keep events that start within the next ``hours`` hours."""

    if not events:
        return []

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc + timedelta(hours=hours)
    filtered: List[Dict[str, Any]] = []

    for event in events:
        commence_time = _parse_datetime(event.get("commence_time"))
        if commence_time and now_utc <= commence_time <= cutoff:
            filtered.append(event)

    if len(filtered) != len(events):
        logger.info(
            "Filtered player props events to %d within %d hours (from %d)",
            len(filtered),
            hours,
            len(events),
        )

    return filtered


class _ResponseStub:
    """Lightweight response wrapper so logging/credit tracking works with aiohttp."""

    def __init__(self, status_code: int, text: str, headers: Dict[str, str]):
        self.status_code = status_code
        self.text = text
        self.headers = headers


class _AsyncResponseWrapper:
    """Wrap a requests response with the minimal aiohttp-like surface we use."""

    def __init__(self, response: requests.Response):
        self._response = response
        self.status = response.status_code
        self.headers = response.headers

    async def text(self) -> str:
        return self._response.text


class _AsyncRequestContext:
    def __init__(self, url: str, params: Dict[str, Any], timeout: int):
        self.url = url
        self.params = params
        self.timeout = timeout
        self._response: Optional[requests.Response] = None

    async def __aenter__(self) -> _AsyncResponseWrapper:
        self._response = await asyncio.to_thread(
            requests.get, self.url, params=self.params, timeout=self.timeout
        )
        return _AsyncResponseWrapper(self._response)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _AsyncRequestsSession:
    """Simple async wrapper around requests for environments without aiohttp."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    async def __aenter__(self) -> "_AsyncRequestsSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str, params: Dict[str, Any]) -> _AsyncRequestContext:
        return _AsyncRequestContext(url, params, self.timeout)


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


def _parse_retry_after(retry_after_header: Optional[str], default_delay: float = 1.0) -> float:
    """Convert Retry-After header values to a sleep duration in seconds."""

    if retry_after_header is None:
        return default_delay

    try:
        parsed = float(retry_after_header)
        if parsed < 0:
            return default_delay
        return parsed
    except (TypeError, ValueError):
        return default_delay


@cached_odds(ttl=10)
def fetch_player_props(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    team: Optional[str] = None,
    player_name: Optional[str] = None,
    event_id: Optional[str] = None,
    use_dummy_data: bool = False,
    dummy_data_generator=None,
    credit_tracker: Optional[ApiCreditTracker] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve player prop markets by first fetching events, then requesting event odds.

    The Odds API serves player props through the event odds endpoint rather than a
    dedicated player props route. We fetch the list of events for the sport, optionally
    filter by team, and then request odds for each event with the desired player prop
    markets enabled.

    The optional player_name filter is currently ignored but accepted for compatibility
    with legacy callers.
    """
    if use_dummy_data and dummy_data_generator:
        return dummy_data_generator(sport_key, markets, bookmaker_keys)

    events_url = f"{BASE_URL}/sports/{sport_key}/events"
    logger.info("Fetching events for player props: url=%s", events_url)
    _log_api_request("player_props_events", events_url, {"apiKey": api_key})
    events_response = requests.get(events_url, params={"apiKey": api_key}, timeout=15)
    _log_api_response("player_props_events", events_response)
    _record_credit_usage(events_response, credit_tracker)
    if events_response.status_code != 200:
        logger.error(
            "Player props events API error: status=%s body=%s",
            events_response.status_code,
            truncate_for_log(events_response.text),
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

    if not event_id:
        events = _filter_events_within_hours(events)

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

    def _get_cached_player_props_result() -> Optional[List[Dict[str, Any]]]:
        """Return any cached player props result for the current arguments."""

        try:
            from services import odds_cache as odds_cache_module
        except Exception:
            return None

        cache_kwargs = {
            "api_key": api_key,
            "sport_key": sport_key,
            "regions": regions,
            "markets": markets,
            "bookmaker_keys": bookmaker_keys,
            "team": team,
            "player_name": player_name,
            "event_id": event_id,
            "use_dummy_data": use_dummy_data,
            "dummy_data_generator": dummy_data_generator,
            "credit_tracker": credit_tracker,
        }

        cache_args = (
            api_key,
            sport_key,
            regions,
            markets,
            bookmaker_keys,
            team,
            player_name,
            event_id,
            use_dummy_data,
            dummy_data_generator,
            credit_tracker,
        )

        now = time.monotonic()
        for key in (
            odds_cache_module._build_cache_key("fetch_player_props", tuple(), cache_kwargs),
            odds_cache_module._build_cache_key("fetch_player_props", cache_args, {}),
        ):
            cached_entry = odds_cache_module._CACHE.get(key)
            if not cached_entry:
                continue

            expires_at, value = cached_entry
            if value is None:
                continue

            if now > expires_at:
                logger.warning(
                    "Using expired cached player props after rate limit exhaustion for sport=%s",
                    sport_key,
                )
            return value

        return None

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
                credit_tracker=credit_tracker,
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

    class _PlayerPropsFallbackRequired(Exception):
        def __init__(self, markets_param: str) -> None:
            super().__init__("Fallback required")
            self.markets_param = markets_param

    async def _fetch_event_player_props(
        session: Any, event: Dict[str, Any]
    ) -> Optional[Any]:
        event_identifier = event.get("id")
        if not event_identifier:
            logger.warning("Skipping event without id: %s", event)
            return None

        event_url = f"{BASE_URL}/sports/{sport_key}/events/{event_identifier}/odds"

        async def _call_with_markets(markets_to_use: List[str], rate_limit_attempt: int = 0) -> Any:
            event_params = odds_params.copy()
            event_params["markets"] = ",".join(markets_to_use)

            logger.info(
                "Calling event odds for player props: url=%s event_id=%s regions=%s markets=%s bookmakers=%s",
                event_url,
                event_identifier,
                regions,
                event_params["markets"],
                bookmaker_keys,
            )
            _log_api_request("player_props_event_odds", event_url, event_params)
            async with session.get(event_url, params=event_params) as resp:
                body = await resp.text()
                response_stub = _ResponseStub(resp.status, body, dict(resp.headers))
                _log_api_response("player_props_event_odds", response_stub)
                _record_credit_usage(response_stub, credit_tracker)

                if resp.status == 422:
                    invalid_markets = _parse_invalid_markets(body)
                    if invalid_markets:
                        remaining = [m for m in markets_to_use if m not in invalid_markets]
                        logger.warning(
                            "Invalid markets for event %s; retrying without: %s",
                            event_identifier,
                            ",".join(sorted(invalid_markets)),
                        )

                        if not remaining:
                            logger.error(
                                "All requested player prop markets were rejected for event %s; skipping",
                                event_identifier,
                            )
                            return None

                        return await _call_with_markets(remaining)

                    if "Invalid markets" in body:
                        logger.warning(
                            "Invalid markets response without details for event %s; using fallback",
                            event_identifier,
                        )
                        raise _PlayerPropsFallbackRequired(event_params["markets"])

                if resp.status == 429:
                    retry_after_header = resp.headers.get("Retry-After")
                    backoff_seconds = _parse_retry_after(retry_after_header)
                    attempt_number = rate_limit_attempt + 1
                    if attempt_number < RATE_LIMIT_MAX_ATTEMPTS:
                        logger.warning(
                            "Rate limited fetching player props for event %s (attempt %s/%s); retrying in %.2fs",
                            event_identifier,
                            attempt_number,
                            RATE_LIMIT_MAX_ATTEMPTS,
                            backoff_seconds,
                        )
                        await asyncio.sleep(backoff_seconds)
                        return await _call_with_markets(markets_to_use, rate_limit_attempt + 1)

                    logger.error(
                        "Rate limit persisted for event %s after %s attempts; switching to fallback",
                        event_identifier,
                        RATE_LIMIT_MAX_ATTEMPTS,
                    )

                    cached_props = _get_cached_player_props_result()
                    if cached_props is not None:
                        logger.info(
                            "Returning cached player props after rate limit exhaustion for event %s",
                            event_identifier,
                        )
                        return cached_props

                    raise _PlayerPropsFallbackRequired(event_params["markets"])

                logger.info(
                    "Event odds API response for player props (event_id=%s): status=%s body=%s",
                    event_identifier,
                    resp.status,
                    truncate_for_log(body),
                )

                if resp.status != 200:
                    logger.error(
                        "Event odds API error for player props: status=%s body=%s",
                        resp.status,
                        truncate_for_log(body),
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "Error from The Odds API when fetching player props: "
                            f"{resp.status}, {body}"
                        ),
                    )

                try:
                    return json.loads(body)
                except json.JSONDecodeError:
                    logger.error(
                        "Failed to parse player props event response for event %s: %s",
                        event_identifier,
                        body,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail="Invalid JSON returned from The Odds API for player props",
                    )

        return await _call_with_markets(list(requested_markets))

    async def _gather_events() -> List[Dict[str, Any]]:
        timeout_seconds = 15
        if aiohttp is not None:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)

            def session_factory():
                return aiohttp.ClientSession(timeout=timeout)
        else:
            def session_factory():
                return _AsyncRequestsSession(timeout=timeout_seconds)

        async with session_factory() as session:
            semaphore = asyncio.Semaphore(EVENT_ODDS_CONCURRENCY_LIMIT)

            async def _bounded_fetch(event: Dict[str, Any]) -> Any:
                async with semaphore:
                    return await _fetch_event_player_props(session, event)

            tasks = [_bounded_fetch(event) for event in events]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        collected: List[Dict[str, Any]] = []

        for result in results:
            if isinstance(result, _PlayerPropsFallbackRequired):
                return _fetch_player_props_via_odds_endpoint(result.markets_param)

            if isinstance(result, Exception):
                if isinstance(result, HTTPException):
                    raise result
                raise HTTPException(status_code=502, detail=str(result))

            if result is None:
                continue

            if isinstance(result, list):
                collected.extend(result)
            else:
                collected.append(result)

        return collected

    collected_events = asyncio.run(_gather_events())

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
