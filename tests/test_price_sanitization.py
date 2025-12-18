from bet_watcher import extract_team_prices
from main import _extract_line_tracker_markets
from services.odds_utils import sanitize_american_price


def test_sanitize_extreme_price_returns_none():
    assert sanitize_american_price(-100000) is None
    assert sanitize_american_price(100000) is None
    assert sanitize_american_price(150) == 150


def test_line_tracker_ignores_extreme_prices():
    event = {
        "home_team": "Home Team",
        "away_team": "Away Team",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Home Team", "price": -100000},
                            {"name": "Away Team", "price": 150},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Home Team", "price": 10000, "point": -3.5},
                            {"name": "Away Team", "price": -110, "point": 3.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 210.5},
                            {"name": "Under", "price": 100000, "point": 210.5},
                        ],
                    },
                ],
            }
        ],
    }

    lines = _extract_line_tracker_markets(
        event=event,
        bookmaker_keys=["draftkings"],
        track_ml=True,
        track_spreads=True,
        track_totals=True,
    )

    dk_lines = lines["draftkings"]
    assert dk_lines["moneyline"]["home_price"] is None
    assert dk_lines["moneyline"]["away_price"] == 150
    assert dk_lines["spread"]["home_price"] is None
    assert dk_lines["spread"]["away_price"] == -110
    assert dk_lines["total"]["over_price"] == -110
    assert dk_lines["total"]["under_price"] is None


def test_bet_watcher_skips_extreme_prices():
    events = [
        {
            "id": "1",
            "home_team": "Home Team",
            "away_team": "Away Team",
            "commence_time": "2024-06-01T00:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Home Team", "price": -100000},
                                {"name": "Away Team", "price": 125},
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    games = extract_team_prices(events, "Home Team", ["draftkings"])

    assert games[0]["prices"]["draftkings"] is None
