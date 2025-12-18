from datetime import datetime, timedelta, timezone

from services.domain import models
from services.player_props_config import PLAYER_PROP_MARKETS_BY_SPORT
from services.value_play_service import ValuePlayService


def test_best_value_expands_all_player_props_once():
    future_start = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    expected_markets = PLAYER_PROP_MARKETS_BY_SPORT["americanfootball_nfl"]

    calls = []

    def recording_provider(**kwargs):
        calls.append(kwargs)
        return [{"id": "event-1"}]

    def noop_validator(events, allow_dummy):
        return None

    def stub_collect(events, market_key, target_book, compare_book):
        return [
            models.ValuePlay(
                event_id=f"{market_key}-id",
                matchup="Team A vs Team B",
                start_time=future_start,
                outcome_name="Player",
                point=None,
                market=market_key,
                novig_price=100,
                novig_reverse_name="Opposite",
                novig_reverse_price=-110,
                book_price=-105,
                ev_percent=1.2,
                hedge_ev_percent=None,
                is_arbitrage=False,
                arb_margin_percent=1.5,
            )
        ]

    service = ValuePlayService(recording_provider, noop_validator, stub_collect)
    query = models.BestValuePlaysQuery(
        sport_keys=["americanfootball_nfl"],
        markets=["all_player_props"],
        target_book="fanduel",
        compare_book="novig",
        max_results=None,
    )

    result = service.get_best_value_plays(query, use_dummy_data=False)

    assert calls[0]["markets"] == expected_markets
    assert len(result.plays) == len(expected_markets)
    assert {play.market for play in result.plays} == set(expected_markets)
    assert all(play.sport_key == "americanfootball_nfl" for play in result.plays)


def test_best_value_filters_out_unsupported_nhl_player_props():
    future_start = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    expected_markets = PLAYER_PROP_MARKETS_BY_SPORT["icehockey_nhl"]

    calls = []

    def recording_provider(**kwargs):
        calls.append(kwargs)
        return [{"id": "event-1"}]

    def noop_validator(events, allow_dummy):
        return None

    def stub_collect(events, market_key, target_book, compare_book):
        return [
            models.ValuePlay(
                event_id=f"{market_key}-id",
                matchup="Team A vs Team B",
                start_time=future_start,
                outcome_name="Player",
                point=None,
                market=market_key,
                novig_price=100,
                novig_reverse_name="Opposite",
                novig_reverse_price=-110,
                book_price=-105,
                ev_percent=1.2,
                hedge_ev_percent=None,
                is_arbitrage=False,
                arb_margin_percent=1.5,
            )
        ]

    service = ValuePlayService(recording_provider, noop_validator, stub_collect)
    query = models.BestValuePlaysQuery(
        sport_keys=["icehockey_nhl"],
        markets=["all_player_props"],
        target_book="fanduel",
        compare_book="novig",
        max_results=None,
    )

    result = service.get_best_value_plays(query, use_dummy_data=False)

    assert calls[0]["markets"] == expected_markets
    assert "player_total_saves" in calls[0]["markets"]
    assert "player_saves" not in calls[0]["markets"]
    assert len(result.plays) == len(expected_markets)
    assert "player_total_saves" in {play.market for play in result.plays}
    assert "player_saves" not in {play.market for play in result.plays}
    assert {play.market for play in result.plays} == set(expected_markets)
