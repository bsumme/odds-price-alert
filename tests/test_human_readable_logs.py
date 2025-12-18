from services.odds_api import build_human_readable_logs


def test_human_logs_emit_once_per_market() -> None:
    payload = [
        {
            "home_team": "Philadelphia Eagles",
            "away_team": "Washington Commanders",
            "bookmakers": [
                {
                    "key": "novig",
                    "title": "Novig",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Philadelphia Eagles", "point": -6.5, "price": -102},
                                {"name": "Washington Commanders", "point": 6.5, "price": -118},
                            ],
                        }
                    ],
                },
                {
                    "key": "fliff",
                    "title": "Fliff",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Philadelphia Eagles", "point": -6.5, "price": -115},
                                {"name": "Washington Commanders", "point": 6.5, "price": -105},
                            ],
                        }
                    ],
                },
            ],
        }
    ]

    messages = build_human_readable_logs(
        payload=payload,
        markets="spreads",
        bookmaker_keys=["novig", "fliff"],
    )

    assert len(messages) == 2
    assert "Commanders vs Philadelphia Eagles" in messages[0]
    assert "market spreads" in messages[0]
    assert "Novig has Philadelphia Eagles -6.5 at -102" in messages[1]
    assert "Fliff has Philadelphia Eagles -6.5 at -115" in messages[1]
