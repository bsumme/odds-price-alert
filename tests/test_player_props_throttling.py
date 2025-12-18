"""Tests for player props throttling and fallback behavior."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest

from services import odds_api
from services.odds_cache import clear_odds_cache


class FakeResponse:
    def __init__(self, status_code: int, text: str, headers: Optional[Dict[str, str]] = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        return json.loads(self.text)


def _future_start_time(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def test_fetch_player_props_retries_on_rate_limit(monkeypatch, caplog):
    clear_odds_cache()
    caplog.set_level(logging.INFO, logger=odds_api.logger.name)

    event_odds_attempts = []

    def fake_requests_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15):
        if url.endswith("/events"):
            return FakeResponse(
                200,
                json.dumps(
                    [
                        {
                            "id": "event-1",
                            "home_team": "Home",
                            "away_team": "Away",
                            "commence_time": _future_start_time(),
                        }
                    ]
                ),
            )

        if "/events/" in url and url.endswith("/odds"):
            event_odds_attempts.append(1)
            if len(event_odds_attempts) == 1:
                return FakeResponse(429, "rate limited", {"Retry-After": "0"})

            return FakeResponse(200, json.dumps([{"id": "event-1", "bookmakers": []}]))

        raise AssertionError(f"Unexpected URL: {url}")

    sleep_calls = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(odds_api, "aiohttp", None)
    monkeypatch.setattr(odds_api.requests, "get", fake_requests_get)
    monkeypatch.setattr(odds_api.asyncio, "sleep", fake_sleep)

    result = odds_api.fetch_player_props(
        api_key="test-key",
        sport_key="basketball_nba",
        regions="us",
        markets="player_points",
        bookmaker_keys=["draftkings"],
    )

    assert result
    assert len(event_odds_attempts) == 2
    assert sleep_calls, "Expected backoff sleep when rate limited"
    assert any("Rate limited" in msg for msg in caplog.messages)
    assert not any("Invalid markets" in msg for msg in caplog.messages)


def test_fetch_player_props_falls_back_after_persistent_rate_limits(monkeypatch, caplog):
    clear_odds_cache()
    caplog.set_level(logging.INFO, logger=odds_api.logger.name)

    def fake_requests_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15):
        if url.endswith("/events"):
            return FakeResponse(
                200,
                json.dumps(
                    [
                        {
                            "id": "event-2",
                            "home_team": "Home",
                            "away_team": "Away",
                            "commence_time": _future_start_time(),
                        }
                    ]
                ),
            )

        if "/events/" in url and url.endswith("/odds"):
            return FakeResponse(429, "rate limited", {"Retry-After": "0"})

        raise AssertionError(f"Unexpected URL: {url}")

    fallback_called = []

    def fake_fetch_odds(**_: Any):
        fallback_called.append(True)
        return [{"id": "fallback-event"}]

    async def fake_sleep(delay: float) -> None:
        # Avoid real delays in tests
        return None

    monkeypatch.setattr(odds_api, "aiohttp", None)
    monkeypatch.setattr(odds_api.requests, "get", fake_requests_get)
    monkeypatch.setattr(odds_api.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(odds_api, "fetch_odds", fake_fetch_odds)

    result = odds_api.fetch_player_props(
        api_key="test-key",
        sport_key="basketball_nba",
        regions="us",
        markets="player_points",
        bookmaker_keys=["draftkings"],
    )

    assert fallback_called, "Expected /odds fallback after persistent rate limits"
    assert result == [{"id": "fallback-event"}]
    assert any("Rate limit persisted" in msg for msg in caplog.messages)
