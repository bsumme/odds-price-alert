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
