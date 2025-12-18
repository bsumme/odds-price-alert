from services.repositories.odds_repository import OddsRepository


def test_live_odds_excludes_player_fields_for_team_markets() -> None:
    captured_kwargs = {}

    def mock_odds_fetcher(**kwargs):
        nonlocal captured_kwargs
        captured_kwargs = kwargs
        return [{"id": "event-1"}]

    repo = OddsRepository(
        api_key_provider=lambda: "api-key",
        region_resolver=lambda _: "us",
        odds_fetcher=mock_odds_fetcher,
        player_props_fetcher=lambda **_: [],
        events_fetcher=lambda **_: [],
        enable_cache=False,
    )

    repo.get_odds_events(
        api_key="live-key",
        sport_key="basketball_nba",
        markets=["h2h", "spreads", "totals"],
        bookmaker_keys=["draftkings"],
        use_dummy_data=False,
        team="Team A",
        player_name="Sample Player",
        event_id="evt-123",
    )

    expected_kwargs = {
        "api_key": "live-key",
        "sport_key": "basketball_nba",
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "bookmaker_keys": ["draftkings"],
        "use_dummy_data": False,
        "credit_tracker": None,
        "gateway": None,
        "gateway_caller": "snapshot_loader",
    }

    assert captured_kwargs == expected_kwargs
    assert "team" not in captured_kwargs
    assert "player_name" not in captured_kwargs
    assert "event_id" not in captured_kwargs
