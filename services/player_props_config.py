"""Shared player prop market configuration and helpers."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

SCHEMA_SPORT_KEY_MAP: Dict[str, List[str]] = {
    "nba_ncaab_wnba": ["basketball_nba", "basketball_ncaab", "basketball_wnba"],
    "nfl_ncaaf_cfl": [
        "americanfootball_nfl",
        "americanfootball_ncaaf",
        "americanfootball_cfl",
    ],
    "mlb": ["baseball_mlb"],
    "nhl": ["icehockey_nhl"],
    "afl": ["aussierules_afl"],
    "rugby_league_nrl": ["rugbyleague_nrl"],
    "soccer": ["soccer"],
}


def _load_schema_player_props() -> Dict[str, Dict[str, str]]:
    schema_path = Path(__file__).resolve().parent.parent / "data" / "schema_definition.json"
    try:
        with schema_path.open("r", encoding="utf-8") as fp:
            schema = json.load(fp)
    except Exception:
        logger.warning("Failed to load schema_definition.json; falling back to legacy props", exc_info=True)
        return {}

    player_props_section = schema.get("player_props") or {}
    if not isinstance(player_props_section, dict):
        logger.warning("Schema player_props section is malformed; falling back to legacy props")
        return {}

    return player_props_section


def _build_markets_from_schema() -> Dict[str, List[str]]:
    player_props_section = _load_schema_player_props()
    if not player_props_section:
        return {}

    markets_by_sport: Dict[str, List[str]] = {}
    for grouping, markets in player_props_section.items():
        mapped_sports = SCHEMA_SPORT_KEY_MAP.get(grouping, [])
        if not mapped_sports:
            continue

        canonical_markets = sorted(markets.keys())
        for sport_key in mapped_sports:
            markets_by_sport[sport_key] = canonical_markets

    return markets_by_sport


# Legacy fallback in case the schema cannot be read (ensures imports still work)
FALLBACK_PLAYER_PROP_MARKETS_BY_SPORT: Dict[str, List[str]] = {
    "basketball_nba": [
        "player_points",
        "player_assists",
        "player_rebounds",
        "player_threes",
    ],
    "americanfootball_nfl": [
        "player_pass_yds",
        "player_reception_yds",
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
    ],
}


# Map legacy or alias markets to their canonical names
PLAYER_PROP_MARKET_ALIASES: Dict[str, str] = {
    # Official Odds API market keys
    "player_passing_yards": "player_pass_yds",
    "player_receiving_yards": "player_reception_yds",
    "player_rushing_yards": "player_rush_yds",
    "player_touchdowns": "player_anytime_td",
    "player_passing_tds": "player_pass_tds",
    "player_powerplay_points": "player_power_play_points",
    # Legacy or shorthand aliases
    "player_pass_yds": "player_pass_yds",
    "player_rec_yds": "player_reception_yds",
    "player_reception_yards": "player_reception_yds",
    "player_rush_yds": "player_rush_yds",
    "player_anytime_td": "player_anytime_td",
    "player_pass_tds": "player_pass_tds",
    "player_saves": "player_total_saves",
}


PLAYER_PROP_MARKETS_BY_SPORT: Dict[str, List[str]] = _build_markets_from_schema() or FALLBACK_PLAYER_PROP_MARKETS_BY_SPORT

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

    if normalized in {"all", "all_player_props"}:
        return True

    return normalized in ALL_PLAYER_PROP_MARKETS


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
