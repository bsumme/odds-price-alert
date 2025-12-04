"""Tests for player props API behaviors."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import main


def test_player_props_returns_404_when_no_lines(monkeypatch):
    monkeypatch.setattr(main, "get_api_key", lambda: "fake-key")

    def fake_fetch_player_props(**_: object):
        return []

    monkeypatch.setattr(main, "fetch_player_props", fake_fetch_player_props)

    payload = main.PlayerPropsRequest(
        sport_key="americanfootball_nfl",
        markets=["player_reception_yds"],
        target_book="fanduel",
        compare_book="novig",
        use_dummy_data=False,
    )

    with pytest.raises(HTTPException) as exc:
        main.get_player_props(payload)

    assert exc.value.status_code == 404
    assert "No player props lines found" in exc.value.detail


def test_player_props_filters_by_event_id(monkeypatch):
    monkeypatch.setattr(main, "get_api_key", lambda: "fake-key")

    def fake_fetch_player_props(**_: object):
        return [
            {"id": "different-event"},
        ]

    monkeypatch.setattr(main, "fetch_player_props", fake_fetch_player_props)

    payload = main.PlayerPropsRequest(
        sport_key="americanfootball_nfl",
        markets=["player_reception_yds"],
        target_book="fanduel",
        compare_book="novig",
        event_id="desired-event",
        use_dummy_data=False,
    )

    with pytest.raises(HTTPException) as exc:
        main.get_player_props(payload)

    assert exc.value.status_code == 404
    assert "event_id=desired-event" in exc.value.detail


def test_list_player_prop_games_with_dummy_data():
    payload = main.PlayerPropGamesRequest(sport_key="basketball_nba", use_dummy_data=True)

    response = main.list_player_prop_games(payload)

    assert response.sport_key == payload.sport_key
    assert response.games
    assert all(game.event_id and game.matchup for game in response.games)


def test_player_props_returns_market_warnings(monkeypatch):
    monkeypatch.setattr(main, "get_api_key", lambda: "fake-key")

    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

    def fake_fetch_player_props(**_: object):
        return [
            {
                "id": "event-1",
                "home_team": "Home Team",
                "away_team": "Away Team",
                "commence_time": future_time,
                "bookmakers": [],
            }
        ]

    monkeypatch.setattr(main, "fetch_player_props", fake_fetch_player_props)

    payload = main.PlayerPropsRequest(
        sport_key="basketball_nba",
        markets=["player_points"],
        target_book="draftkings",
        compare_book="novig",
        use_dummy_data=False,
    )

    response = main.get_player_props(payload)

    assert response.warnings
    assert any("Available player prop markets" in msg for msg in response.warnings)
    assert any("Markets with prices from both" in msg for msg in response.warnings)
