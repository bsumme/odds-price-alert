"""Shared player prop market configuration and helpers."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set

# Map legacy or alias markets to their canonical names
PLAYER_PROP_MARKET_ALIASES: Dict[str, str] = {
    # Official Odds API market keys
    "player_passing_yards": "player_pass_yds",
    "player_receiving_yards": "player_rec_yds",
    "player_rushing_yards": "player_rush_yds",
    "player_touchdowns": "player_anytime_td",
    "player_passing_tds": "player_pass_tds",
    "player_powerplay_points": "player_power_play_points",
    # Legacy or shorthand aliases
    "player_pass_yds": "player_pass_yds",
    "player_rec_yds": "player_rec_yds",
    "player_reception_yards": "player_rec_yds",
    "player_rush_yds": "player_rush_yds",
    "player_anytime_td": "player_anytime_td",
    "player_pass_tds": "player_pass_tds",
}

# Define the supported player prop markets for each sport
PLAYER_PROP_MARKETS_BY_SPORT: Dict[str, List[str]] = {
    "basketball_nba": [
        "player_points",
        "player_assists",
        "player_rebounds",
        "player_threes",
    ],
    "americanfootball_nfl": [
        "player_pass_yds",
        "player_rec_yds",
        "player_rush_yds",
        "player_anytime_td",
        "player_pass_tds",
    ],
    "icehockey_nhl": [
        "player_points",
        "player_goals",
        "player_assists",
        "player_shots_on_goal",
        "player_power_play_points",
        "player_blocks",
        "player_saves",
    ],
}

SUPPORTED_PLAYER_PROP_SPORTS: Set[str] = set(PLAYER_PROP_MARKETS_BY_SPORT.keys())

ALL_PLAYER_PROP_MARKETS: List[str] = sorted(
    {m for markets in PLAYER_PROP_MARKETS_BY_SPORT.values() for m in markets}
)


def normalize_player_prop_market(market: str) -> Optional[str]:
    """Return the canonical player prop market key for the provided value."""

    if not market:
        return None
    key = market.strip()
    return PLAYER_PROP_MARKET_ALIASES.get(key, key)


def is_player_prop_market(market: str) -> bool:
    """Check whether a market string refers to player props (including aliases)."""

    normalized = normalize_player_prop_market(market)
    if not normalized:
        return False
    return normalized.startswith("player_") or normalized in {"all", "all_player_props"}


def expand_player_prop_markets(sport_key: str, markets: Iterable[str]) -> List[str]:
    """Expand aliases and the 'all_player_props' shortcut for a sport."""

    expanded: List[str] = []
    seen: set[str] = set()

    for market in markets:
        normalized = normalize_player_prop_market(market)
        if not normalized or normalized in seen:
            continue

        if normalized in ("all", "all_player_props"):
            sport_markets = PLAYER_PROP_MARKETS_BY_SPORT.get(sport_key, ALL_PLAYER_PROP_MARKETS)
            for sport_market in sport_markets:
                if sport_market not in seen:
                    expanded.append(sport_market)
                    seen.add(sport_market)
            continue

        expanded.append(normalized)
        seen.add(normalized)

    return expanded
