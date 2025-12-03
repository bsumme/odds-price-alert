"""Tests for player props API behaviors."""

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
        markets=["player_receiving_yards"],
        target_book="fanduel",
        compare_book="novig",
        use_dummy_data=False,
    )

    with pytest.raises(HTTPException) as exc:
        main.get_player_props(payload)

    assert exc.value.status_code == 404
    assert "No player props lines found" in exc.value.detail
