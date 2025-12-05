from hedge_watcher import filter_by_margin, format_play_summary, play_identifier
from main import BestValuePlayOutcome


def _sample_play(margin: float, event_id: str = "evt1") -> BestValuePlayOutcome:
    return BestValuePlayOutcome(
        sport_key="basketball_nba",
        market="h2h",
        event_id=event_id,
        matchup="Team A vs Team B",
        start_time="2024-11-20T20:00:00Z",
        outcome_name="Team A",
        point=None,
        novig_price=-110,
        novig_reverse_name="Team B",
        novig_reverse_price=110,
        book_price=-105,
        ev_percent=2.5,
        hedge_ev_percent=None,
        is_arbitrage=True,
        arb_margin_percent=margin,
    )


def test_filter_by_margin_filters_out_low_values() -> None:
    plays = [_sample_play(1.5), _sample_play(-0.5, event_id="evt2")]

    filtered = filter_by_margin(plays, min_margin_percent=0)

    assert len(filtered) == 1
    assert filtered[0].arb_margin_percent == 1.5


def test_play_identifier_uses_event_market_and_outcome() -> None:
    play = _sample_play(0.5)

    identifier = play_identifier(play)

    assert "evt1" in identifier
    assert "h2h" in identifier
    assert "Team A" in identifier


def test_format_play_summary_includes_margin_and_odds() -> None:
    play = _sample_play(1.25)

    summary = format_play_summary(play)

    assert "margin 1.25%" in summary
    assert "@ -105" in summary
    assert "hedge +110" in summary
