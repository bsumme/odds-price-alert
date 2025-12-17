"""Tests for player props API behaviors."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import main
import services.odds_api as odds_api


def test_player_props_returns_404_when_no_lines(monkeypatch):
    monkeypatch.setattr(main, "get_api_key", lambda: "fake-key")

    def fake_fetch_player_props(**_: object):
        return []

    monkeypatch.setattr(main, "fetch_player_props", fake_fetch_player_props)

    payload = main.PlayerPropsRequest(
        sport_key="americanfootball_nfl",
        markets=["player_rec_yds"],
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
        markets=["player_rec_yds"],
        target_book="fanduel",
        compare_book="novig",
        event_id="desired-event",
        use_dummy_data=False,
    )

    with pytest.raises(HTTPException) as exc:
        main.get_player_props(payload)

    assert exc.value.status_code == 404
    assert "event_id=desired-event" in exc.value.detail


def test_player_props_rejects_mma_requests():
    payload = main.PlayerPropsRequest(
        sport_key="mma_mixed_martial_arts",
        markets=["player_points"],
        target_book="fanduel",
        compare_book="novig",
        use_dummy_data=False,
    )

    with pytest.raises(HTTPException) as exc:
        main.get_player_props(payload)

    assert exc.value.status_code == 400
    assert "fight winner odds" in exc.value.detail


def test_list_player_prop_games_with_dummy_data():
    payload = main.PlayerPropGamesRequest(sport_key="basketball_nba", use_dummy_data=True)

    response = main.list_player_prop_games(payload)

    assert response.sport_key == payload.sport_key
    assert response.games
    assert all(game.event_id and game.matchup for game in response.games)
    assert response.last_update


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


def test_player_props_includes_last_update(monkeypatch):
    monkeypatch.setattr(main, "get_api_key", lambda: "fake-key")

    latest_update = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )

    def fake_fetch_player_props(**_: object):
        return [
            {
                "id": "event-1",
                "home_team": "Home Team",
                "away_team": "Away Team",
                "commence_time": latest_update,
                "bookmakers": [],
                "last_update": latest_update,
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

    assert response.last_update == latest_update


def test_extract_latest_update_timestamp_prefers_newest():
    older = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    newer = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")

    events = [
        {
            "last_update": older,
            "bookmakers": [
                {
                    "last_update": older,
                    "markets": [
                        {
                            "last_update": older,
                            "outcomes": [
                                {"name": "Over", "last_update": older},
                                {"name": "Under", "last_update": newer},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    assert main._extract_latest_update_timestamp(events) == newer


def test_filters_events_within_48_hours():
    now = datetime.now(timezone.utc)
    events = [
        {"id": "soon", "commence_time": (now + timedelta(hours=2)).isoformat()},
        {"id": "far", "commence_time": (now + timedelta(hours=60)).isoformat()},
        {"id": "past", "commence_time": (now - timedelta(hours=1)).isoformat()},
    ]

    filtered = odds_api._filter_events_within_hours(events, hours=48)

    remaining_ids = {event["id"] for event in filtered}
    assert remaining_ids == {"soon"}


def test_player_prop_arbitrage_requires_matching_player_name():
    start_time = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat().replace(
        "+00:00", "Z"
    )

    events = [
        {
            "id": "event-1",
            "home_team": "Home Team",
            "away_team": "Away Team",
            "commence_time": start_time,
            "bookmakers": [
                {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "last_update": start_time,
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {
                                    "name": "Under",
                                    "price": -125,
                                    "point": 19.5,
                                    "description": "Jaren Jackson Jr",
                                },
                                {
                                    "name": "Over",
                                    "price": 105,
                                    "point": 19.5,
                                    "description": "Jaren Jackson Jr",
                                },
                            ],
                        }
                    ],
                },
                {
                    "key": "novig",
                    "title": "Novig",
                    "last_update": start_time,
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "price": 300,
                                    "point": 19.5,
                                    "description": "Donte DiVincenzo",
                                },
                                {
                                    "name": "Under",
                                    "price": -400,
                                    "point": 19.5,
                                    "description": "Donte DiVincenzo",
                                },
                            ],
                        }
                    ],
                },
            ],
        }
    ]

    plays = main.collect_value_plays(events, "player_points", "fanduel", "novig")

    assert plays == []
