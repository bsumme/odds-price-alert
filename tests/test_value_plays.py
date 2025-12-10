from datetime import datetime, timedelta, timezone

from main import collect_value_plays


def test_moneyline_skips_when_target_book_has_no_posted_prices():
    future_start = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    events = [
        {
            "id": "event-1",
            "home_team": "Home Team",
            "away_team": "Away Team",
            "commence_time": future_start,
            "bookmakers": [
                {
                    "key": "novig",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Home Team", "price": -120},
                                {"name": "Away Team", "price": 110},
                            ],
                        }
                    ],
                },
                {
                    "key": "fliff",
                    "markets": [
                        {
                            "key": "h2h",
                            # Only one side has a posted price; treat as missing moneyline.
                            "outcomes": [
                                {"name": "Home Team", "price": -125},
                            ],
                        }
                    ],
                },
            ],
        }
    ]

    plays = collect_value_plays(events, market_key="h2h", target_book="fliff", compare_book="novig")

    assert plays == []


def test_hedge_fields_omitted_when_compare_book_is_novig():
    future_start = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat().replace("+00:00", "Z")

    events = [
        {
            "id": "event-2",
            "home_team": "Team A",
            "away_team": "Team B",
            "commence_time": future_start,
            "bookmakers": [
                {
                    "key": "novig",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": -125},
                                {"name": "Team B", "price": 115},
                            ],
                        }
                    ],
                },
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team A", "price": -110},
                                {"name": "Team B", "price": 100},
                            ],
                        }
                    ],
                },
            ],
        }
    ]

    plays = collect_value_plays(events, market_key="h2h", target_book="draftkings", compare_book="novig")

    assert len(plays) == 2
    for play in plays:
        assert play.novig_reverse_name in {"Team A", "Team B"}
        assert play.novig_reverse_price in {-125, 115}
        assert play.hedge_ev_percent is not None
        assert play.arb_margin_percent is not None


def test_skips_when_compare_book_lacks_opposite_side():
    future_start = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat().replace("+00:00", "Z")

    events = [
        {
            "id": "event-3",
            "home_team": "Team C",
            "away_team": "Team D",
            "commence_time": future_start,
            "bookmakers": [
                {
                    "key": "novig",
                    "markets": [
                        {
                            "key": "h2h",
                            # Only one side posted; cannot hedge
                            "outcomes": [
                                {"name": "Team C", "price": -140},
                            ],
                        }
                    ],
                },
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Team C", "price": -115},
                                {"name": "Team D", "price": 105},
                            ],
                        }
                    ],
                },
            ],
        }
    ]

    plays = collect_value_plays(events, market_key="h2h", target_book="draftkings", compare_book="novig")

    assert plays == []
