"""Configuration for snapshot fetch cycles."""
from __future__ import annotations

import os
from typing import Dict, List

from services.player_props_config import PLAYER_PROP_MARKETS_BY_SPORT

DEFAULT_SNAPSHOT_SPORTS: List[str] = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "icehockey_nhl",
]

DEFAULT_MARKETS_BY_SPORT: Dict[str, List[str]] = {
    "basketball_nba": ["h2h", "spreads", "totals"],
    "americanfootball_nfl": ["h2h", "spreads", "totals"],
    "baseball_mlb": ["h2h", "spreads", "totals"],
    "icehockey_nhl": ["h2h", "spreads", "totals"],
}

DEFAULT_PLAYER_PROP_MARKETS_BY_SPORT: Dict[str, List[str]] = {
    sport: PLAYER_PROP_MARKETS_BY_SPORT[sport]
    for sport in DEFAULT_SNAPSHOT_SPORTS
    if sport in PLAYER_PROP_MARKETS_BY_SPORT
}

DEFAULT_BOOKMAKERS: List[str] = ["draftkings", "fanduel", "novig", "fliff"]

SNAPSHOT_INTERVAL_SECONDS = int(os.getenv("SNAPSHOT_INTERVAL_SECONDS", "180"))
