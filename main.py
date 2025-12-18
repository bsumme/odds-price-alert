import json
import logging
import os
import random
import re
import sys
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import ClassVar, List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

# Import shared utilities
from services.odds_api import (
    get_api_key,
    fetch_odds,
    fetch_player_props,
    fetch_sport_events,
    BASE_URL,
    ApiCreditTracker,
)
from services.domain import mappers as domain_mappers
from services.odds_service import OddsService
from services.odds_utils import (
    american_to_decimal,
    estimate_ev_percent,
    points_match,
    apply_vig_adjustment,
    decimal_to_american,
    sanitize_american_price,
)
from services.player_props_config import (
    ALL_PLAYER_PROP_MARKETS as CONFIG_ALL_PLAYER_PROP_MARKETS,
    PLAYER_PROP_MARKET_ALIASES as CONFIG_PLAYER_PROP_MARKET_ALIASES,
    PLAYER_PROP_MARKETS_BY_SPORT as CONFIG_PLAYER_PROP_MARKETS_BY_SPORT,
    SUPPORTED_PLAYER_PROP_SPORTS as CONFIG_SUPPORTED_PLAYER_PROP_SPORTS,
    expand_player_prop_markets,
)
from services.value_play_service import ValuePlayService
from services.repositories.odds_repository import OddsRepository
from utils.formatting import format_start_time_est
from utils.logging_control import apply_trace_level, should_log_trace_entries

# Use the uvicorn logger so messages show alongside existing INFO entries.
logger = logging.getLogger("uvicorn.error")
TRACE_LEVEL = apply_trace_level(logger)
TRACE_LOGGING_ENABLED = should_log_trace_entries(TRACE_LEVEL)

# Odds API subscription limit for calculating credit usage display
API_REQUEST_LIMIT = 20_000

# Featured SGP helper defaults
FEATURED_SPORTS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "icehockey_nhl",
]
FEATURED_MARKETS = ["h2h", "spreads", "totals"]
FEATURED_LOOKAHEAD_HOURS = 36


def _dummy_data_flag_enabled() -> bool:
    """Return True when the app was launched with a dummy-data flag or env var."""

    normalized_args = {arg.lower() for arg in sys.argv[1:]}
    if {"-dummydata", "--dummydata"} & normalized_args:
        return True

    env_flag = os.getenv("DUMMY_DATA", "")
    return env_flag.lower() in {"1", "true", "yes"}


DUMMY_DATA_ENABLED = _dummy_data_flag_enabled()

# -------------------------------------------------------------------
# Pydantic Models
# -------------------------------------------------------------------


class PriceOut(BaseModel):
    bookmaker_key: str
    bookmaker_name: str
    price: Optional[int]  # the best price for that side, if available
    verified_from_api: bool = False


class BetRequest(BaseModel):
    """
    Represents a single bet the user cares about in the watcher UI.
    For example: "NBA, spreads, Golden State Warriors -3.5"
    """
    sport_key: str
    market: str  # "h2h", "spreads", "totals", or a prop like "player_points"
    team: str    # for props, this might be a player name instead
    point: Optional[float] = None
    bookmaker_keys: List[str]  # e.g. ["draftkings", "fanduel", "novig"]


class OddsRequest(BaseModel):
    bets: List[BetRequest]
    use_dummy_data: bool = False


class SingleBetOdds(BaseModel):
    sport_key: str
    market: str
    team: str
    point: Optional[float]
    prices: List[PriceOut]  # one PriceOut per bookmaker we asked for


class OddsResponse(BaseModel):
    bets: List[SingleBetOdds]


class ValuePlayOutcome(BaseModel):
    event_id: str
    matchup: str
    start_time: Optional[str]
    outcome_name: str        # e.g. "New York Knicks" or "LeBron James"
    point: Optional[float]   # spread/total/prop line (if applicable)
    market: Optional[str] = None
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    book_prices: Dict[str, Optional[int]] = Field(default_factory=dict)
    opposing_prices: Dict[str, Optional[int]] = Field(default_factory=dict)
    ev_percent: float        # estimated edge in percent (vs Novig same side)
    hedge_ev_percent: Optional[float] = None  # Hedge score (arb margin %) when an opposite side exists
    is_arbitrage: bool = False
    arb_margin_percent: Optional[float] = None  # % margin of arb if present (book vs Novig opposite)


class ValuePlaysResponse(BaseModel):
    target_book: str
    compare_book: str
    market: str
    plays: List[ValuePlayOutcome]


class ValuePlaysRequest(BaseModel):
    """
    Request body for /api/value-plays:
      - sport_key: e.g. "basketball_nba"
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "fanduel" (the book to compare against)
      - market: "h2h", "spreads", "totals", or "player_points"
      - use_dummy_data: if True, use mock data instead of real API calls
    """
    sport_key: str
    target_book: str
    compare_book: str
    market: str
    use_dummy_data: bool = False
    max_results: Optional[int] = None


class BestValuePlayOutcome(BaseModel):
    """Extended value play outcome with sport and market info"""
    sport_key: str
    market: str
    event_id: str
    matchup: str
    start_time: Optional[str]
    outcome_name: str
    point: Optional[float]
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    ev_percent: float
    hedge_ev_percent: Optional[float] = None
    is_arbitrage: bool = False
    arb_margin_percent: Optional[float] = None


class BestValuePlaysRequest(BaseModel):
    """
    Request body for /api/best-value-plays:
      - sport_keys: list of sports to search, e.g. ["basketball_nba", "americanfootball_nfl"]
      - markets: list of markets to search, e.g. ["h2h", "spreads", "totals"]
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "novig" (the book to compare against)
      - max_results: maximum number of results to return
      - use_dummy_data: if True, use mock data instead of real API calls
    """
    sport_keys: List[str]
    markets: List[str]
    target_book: str
    compare_book: str
    max_results: Optional[int] = 50
    use_dummy_data: bool = False


class BestValuePlaysResponse(BaseModel):
    target_book: str
    compare_book: str
    plays: List[BestValuePlayOutcome]
    used_dummy_data: bool = False


class PlayerPropsRequest(BaseModel):
    """
    Request body for /api/player-props:
      - sport_key: e.g. "basketball_nba" or "americanfootball_nfl"
      - team: team name to filter by (optional, can be None to search all teams)
      - player_name: deprecated and currently ignored; retained for backward compatibility
      - markets: list of player prop markets like "player_points", "player_assists",
        "player_rebounds", etc.
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "novig" (the book to compare against)
      - use_dummy_data: if True, use mock data instead of real API calls
    """
    sport_key: str
    team: Optional[str] = None
    player_name: Optional[str] = None
    event_id: Optional[str] = None
    markets: List[str]
    target_book: str
    compare_book: str
    use_dummy_data: bool = False

    PLAYER_PROP_MARKET_ALIASES: ClassVar[Dict[str, str]] = CONFIG_PLAYER_PROP_MARKET_ALIASES
    PLAYER_PROP_MARKETS_BY_SPORT: ClassVar[Dict[str, List[str]]] = CONFIG_PLAYER_PROP_MARKETS_BY_SPORT
    SUPPORTED_PLAYER_PROP_SPORTS: ClassVar[Set[str]] = CONFIG_SUPPORTED_PLAYER_PROP_SPORTS
    ALL_PLAYER_PROP_MARKETS: ClassVar[List[str]] = CONFIG_ALL_PLAYER_PROP_MARKETS

    @model_validator(mode="before")
    def ensure_markets(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Allow legacy single-market payloads while enforcing at least one market."""
        if data is None:
            raise ValueError("Payload is required")

        # Support legacy payloads that used a single 'market' field.
        if "markets" not in data or data.get("markets") is None:
            legacy_market = data.get("market")
            if legacy_market:
                data["markets"] = [legacy_market]

        markets = data.get("markets")
        if not markets:
            raise ValueError("At least one market must be specified for player props")

        # Normalize to a unique, ordered list of strings.
        normalized: List[str] = []
        for m in markets:
            if not m:
                continue
            if not isinstance(m, str):
                raise ValueError("Market entries must be strings")
            trimmed = m.strip()
            if trimmed and trimmed not in normalized:
                normalized.append(trimmed)

        if not normalized:
            raise ValueError("At least one valid market must be provided")

        data["markets"] = normalized
        return data

    def resolve_markets(self) -> List[str]:
        """
        Expand aliases and the special "all_player_props" flag to the supported markets
        for the selected sport. Falls back to all known player prop markets if the
        sport is unrecognized.
        """

        expanded = expand_player_prop_markets(self.sport_key, self.markets)

        if not expanded:
            raise ValueError("At least one valid market must be provided")

        return expanded


def ensure_player_props_supported(sport_key: str) -> None:
    """Raise an HTTP error when player props are not available for a sport."""

    if sport_key not in PlayerPropsRequest.SUPPORTED_PLAYER_PROP_SPORTS:
        supported = ", ".join(sorted(PlayerPropsRequest.SUPPORTED_PLAYER_PROP_SPORTS))
        raise HTTPException(
            status_code=400,
            detail=(
                f"Player props are not available for sport '{sport_key}'. "
                f"Supported sports: {supported}. The Odds API only provides "
                "fight winner odds for MMA and does not expose traditional player props "
                "for this sport."
            ),
        )


class PlayerPropArbitrageRequest(BaseModel):
    """Search every supported player-prop sport for arbitrage vs a comparison book."""

    sport_keys: Optional[List[str]] = None
    target_books: Optional[List[str]] = None
    compare_book: str = "novig"
    max_results: Optional[int] = 100
    use_dummy_data: bool = False


class PlayerPropArbOutcome(ValuePlayOutcome):
    sport_key: str
    target_book: str


class PlayerPropArbitrageResponse(BaseModel):
    compare_book: str
    target_books: List[str]
    plays: List[PlayerPropArbOutcome]
    used_dummy_data: bool = False
    warnings: List[str] = []


class PlayerPropsResponse(BaseModel):
    target_book: str
    compare_book: str
    markets: List[str]
    plays: List[ValuePlayOutcome]
    warnings: List[str] = Field(default_factory=list)
    last_update: Optional[str] = None


class ParlayBuilderRequest(BestValuePlaysRequest):
    """Request to build a parlay from the highest hedge EV plays."""

    parlay_size: int = Field(default=3, ge=2, le=6)
    boost_percent: float = Field(default=30.0, ge=20.0, le=100.0)


class ParlayBuilderResponse(BaseModel):
    target_book: str
    compare_book: str
    parlay_legs: List[BestValuePlayOutcome]
    combined_decimal_odds: Optional[float]
    combined_american_odds: Optional[int]
    boost_percent: float
    boosted_decimal_odds: Optional[float]
    boosted_american_odds: Optional[int]
    notes: List[str] = Field(default_factory=list)
    used_dummy_data: bool = False


class SGPSuggestion(BaseModel):
    event_id: str
    matchup: str
    start_time: Optional[str]
    legs: List[ValuePlayOutcome]
    combined_decimal_odds: Optional[float]
    combined_american_odds: Optional[int]
    boost_percent: float
    boosted_decimal_odds: Optional[float]
    boosted_american_odds: Optional[int]
    note: Optional[str] = None


class SGPBuilderRequest(BaseModel):
    """Request to build same-game parlay recommendations from player props."""

    sport_key: str
    event_id: Optional[str] = None
    target_book: str
    compare_book: str
    boost_percent: float = Field(default=30.0, ge=20.0, le=100.0)
    use_dummy_data: bool = False
    avoid_correlation: bool = True
    min_total_american_odds: int = Field(default=100)
    max_total_american_odds: int = Field(default=20000)


class SGPBuilderResponse(BaseModel):
    sport_key: str
    target_book: str
    compare_book: str
    best_sgp: Optional[SGPSuggestion] = None
    uncorrelated_sgp: Optional[SGPSuggestion] = None
    warnings: List[str] = Field(default_factory=list)


class PlayerPropEvent(BaseModel):
    event_id: str
    matchup: str
    commence_time: Optional[str] = None


class PlayerPropGamesRequest(BaseModel):
    sport_key: str
    use_dummy_data: bool = False


class PlayerPropGamesResponse(BaseModel):
    sport_key: str
    games: List[PlayerPropEvent]
    last_update: Optional[str] = None


class PlayerPropMarketsRequest(BaseModel):
    sport_key: str
    target_book: Optional[str] = "draftkings"
    compare_book: Optional[str] = "novig"
    use_dummy_data: bool = False


class PlayerPropMarketsResponse(BaseModel):
    sport_key: str
    available_markets: List[str]


class FeaturedGame(BaseModel):
    sport_key: str
    event_id: str
    matchup: str
    commence_time: Optional[str] = None
    popularity_score: float = 0.0
    available_markets: List[str] = Field(default_factory=list)


class FeaturedGamesResponse(BaseModel):
    games: List[FeaturedGame]
    used_dummy_data: bool = False


def get_textbelt_api_key() -> Optional[str]:
    """Get the Textbelt API key from environment variable. Returns None if not set."""
    return os.getenv("TEXTBELT_API_KEY")




def generate_dummy_odds_data(
    sport_key: str,
    markets: str,
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Generate simple dummy/mock odds data for development.

    This version intentionally mirrors the shape of real Odds API responses
    captured in logs/real_odds_api_responses.jsonl. The goal is to keep the
    numbers realistic while ensuring every market type (moneyline, spreads,
    totals) has a few clear value spots when compared to Novig.
    """
    sample_events = {
        "basketball_nba": [
            {
                "home_team": "Washington Wizards",
                "away_team": "Milwaukee Bucks",
                "commence_in_hours": 6,
                "bookmakers": {
                    "novig": {
                        "h2h": {"home": -145, "away": +130},
                        "spreads": {"point": -4.5, "home_price": -112, "away_price": -102},
                        "totals": {"point": 231.5, "over_price": -112, "under_price": -108},
                    },
                    "fliff": {
                        "h2h": {"home": -135, "away": +145},
                        "spreads": {"point": -4.5, "home_price": -105, "away_price": -115},
                        "totals": {"point": 231.5, "over_price": -105, "under_price": -110},
                    },
                    "draftkings": {
                        "h2h": {"home": -140, "away": +135},
                        "spreads": {"point": -4.5, "home_price": -108, "away_price": -112},
                        "totals": {"point": 231.5, "over_price": -110, "under_price": -110},
                    },
                },
            },
            {
                "home_team": "Denver Nuggets",
                "away_team": "Phoenix Suns",
                "commence_in_hours": 30,
                "bookmakers": {
                    "novig": {
                        "h2h": {"home": -125, "away": +118},
                        "spreads": {"point": -3.5, "home_price": -110, "away_price": -104},
                        "totals": {"point": 227.5, "over_price": -115, "under_price": -105},
                    },
                    "fliff": {
                        "h2h": {"home": -120, "away": +125},
                        "spreads": {"point": -3.5, "home_price": -102, "away_price": -110},
                        "totals": {"point": 227.5, "over_price": -108, "under_price": -104},
                    },
                    "draftkings": {
                        "h2h": {"home": -122, "away": +122},
                        "spreads": {"point": -3.5, "home_price": -106, "away_price": -108},
                        "totals": {"point": 227.5, "over_price": -112, "under_price": -108},
                    },
                },
            },
        ],
        "americanfootball_nfl": [
            {
                "home_team": "San Francisco 49ers",
                "away_team": "Dallas Cowboys",
                "commence_in_hours": 54,
                "bookmakers": {
                    "novig": {
                        "h2h": {"home": -175, "away": +155},
                        "spreads": {"point": -3.5, "home_price": -112, "away_price": -102},
                        "totals": {"point": 44.5, "over_price": -110, "under_price": -108},
                    },
                    "fliff": {
                        "h2h": {"home": -165, "away": +165},
                        "spreads": {"point": -3.5, "home_price": -104, "away_price": -112},
                        "totals": {"point": 44.5, "over_price": -106, "under_price": -104},
                    },
                    "draftkings": {
                        "h2h": {"home": -170, "away": +160},
                        "spreads": {"point": -3.5, "home_price": -108, "away_price": -110},
                        "totals": {"point": 44.5, "over_price": -108, "under_price": -110},
                    },
                },
            },
            {
                "home_team": "Buffalo Bills",
                "away_team": "Kansas City Chiefs",
                "commence_in_hours": 74,
                "bookmakers": {
                    "novig": {
                        "h2h": {"home": -115, "away": +108},
                        "spreads": {"point": -2.5, "home_price": -110, "away_price": -104},
                        "totals": {"point": 48.5, "over_price": -112, "under_price": -102},
                    },
                    "fliff": {
                        "h2h": {"home": -110, "away": +118},
                        "spreads": {"point": -2.5, "home_price": -102, "away_price": -110},
                        "totals": {"point": 48.5, "over_price": -106, "under_price": -104},
                    },
                    "draftkings": {
                        "h2h": {"home": -112, "away": +114},
                        "spreads": {"point": -2.5, "home_price": -104, "away_price": -112},
                        "totals": {"point": 48.5, "over_price": -108, "under_price": -106},
                    },
                },
            },
        ],
    }

    requested_markets = markets.split(",") if "," in markets else [markets]
    now = datetime.now(timezone.utc)
    events: List[Dict[str, Any]] = []

    def build_market_payload(market_key: str, market_values: Dict[str, Any], home: str, away: str) -> Dict[str, Any]:
        if market_key == "h2h":
            return {
                "key": market_key,
                "outcomes": [
                    {"name": home, "price": market_values["home"]},
                    {"name": away, "price": market_values["away"]},
                ],
            }
        if market_key == "spreads":
            point = market_values["point"]
            return {
                "key": market_key,
                "outcomes": [
                    {"name": home, "price": market_values["home_price"], "point": point},
                    {"name": away, "price": market_values["away_price"], "point": -point},
                ],
            }
        if market_key == "totals":
            point = market_values["point"]
            return {
                "key": market_key,
                "outcomes": [
                    {"name": "Over", "price": market_values["over_price"], "point": point},
                    {"name": "Under", "price": market_values["under_price"], "point": point},
                ],
            }
        return {}

    sport_events = sample_events.get(sport_key)
    if not sport_events:
        # Fallback: generate a single simple event with generic teams so callers never break
        sport_events = [
            {
                "home_team": "Home Team",
                "away_team": "Away Team",
                "commence_in_hours": 24,
                "bookmakers": {
                    "novig": {
                        "h2h": {"home": -120, "away": +110},
                        "spreads": {"point": -3.0, "home_price": -110, "away_price": -104},
                        "totals": {"point": 46.5, "over_price": -112, "under_price": -108},
                    },
                    "fliff": {
                        "h2h": {"home": -115, "away": +120},
                        "spreads": {"point": -3.0, "home_price": -104, "away_price": -110},
                        "totals": {"point": 46.5, "over_price": -106, "under_price": -104},
                    },
                },
            }
        ]

    for idx, event in enumerate(sport_events):
        home = event["home_team"]
        away = event["away_team"]
        commence_time = (
            now + timedelta(hours=event.get("commence_in_hours", 24))
        ).isoformat().replace("+00:00", "Z")

        bookmakers: List[Dict[str, Any]] = []
        for book_key in bookmaker_keys:
            book_data = event["bookmakers"].get(book_key)
            if not book_data:
                continue

            markets_payload = []
            for market_key in requested_markets:
                if market_key not in book_data:
                    continue
                payload = build_market_payload(market_key, book_data[market_key], home, away)
                if payload:
                    markets_payload.append(payload)

            if markets_payload:
                bookmakers.append({
                    "key": book_key,
                    "title": book_key.title(),
                    "markets": markets_payload,
                })

        if not bookmakers:
            continue

        events.append({
            "id": f"dummy_{sport_key}_{idx}_{int(now.timestamp())}",
            "sport_key": sport_key,
            "home_team": home,
            "away_team": away,
            "commence_time": commence_time,
            "bookmakers": bookmakers,
        })

    return events

def generate_dummy_player_props_data(
    sport_key: str,
    markets: List[str],
    team: Optional[str],
    player_name: Optional[str],
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Generate dummy player props data for development.
    """

    def _slugify(value: str) -> str:
        return value.replace(" ", "_").lower()

    # Sample players by sport and team
    nba_players = {
        "Lakers": ["LeBron James", "Anthony Davis", "D'Angelo Russell", "Austin Reaves"],
        "Warriors": ["Stephen Curry", "Klay Thompson", "Draymond Green", "Andrew Wiggins"],
        "Celtics": ["Jayson Tatum", "Jaylen Brown", "Kristaps Porzingis", "Derrick White"],
        "Heat": ["Jimmy Butler", "Bam Adebayo", "Tyler Herro", "Duncan Robinson"],
        "Nuggets": ["Nikola Jokic", "Jamal Murray", "Michael Porter Jr.", "Aaron Gordon"],
        "Suns": ["Devin Booker", "Kevin Durant", "Bradley Beal", "Jusuf Nurkic"],
        "Bucks": ["Giannis Antetokounmpo", "Damian Lillard", "Khris Middleton", "Brook Lopez"],
        "76ers": ["Joel Embiid", "Tyrese Maxey", "Tobias Harris", "James Harden"],
        "Mavericks": ["Luka Doncic", "Kyrie Irving", "Tim Hardaway Jr.", "Grant Williams"],
        "Clippers": ["Kawhi Leonard", "Paul George", "James Harden", "Russell Westbrook"],
    }

    nfl_players = {
        "Chiefs": ["Patrick Mahomes", "Travis Kelce", "Isiah Pacheco", "Rashee Rice"],
        "Bills": ["Josh Allen", "Stefon Diggs", "James Cook", "Dawson Knox"],
        "49ers": ["Brock Purdy", "Christian McCaffrey", "Deebo Samuel", "George Kittle"],
        "Cowboys": ["Dak Prescott", "CeeDee Lamb", "Tony Pollard", "Jake Ferguson"],
        "Ravens": ["Lamar Jackson", "Mark Andrews", "Gus Edwards", "Zay Flowers"],
        "Bengals": ["Joe Burrow", "Ja'Marr Chase", "Joe Mixon", "Tee Higgins"],
        "Dolphins": ["Tua Tagovailoa", "Tyreek Hill", "Raheem Mostert", "Jaylen Waddle"],
        "Jets": ["Aaron Rodgers", "Breece Hall", "Garrett Wilson", "Tyler Conklin"],
        "Eagles": ["Jalen Hurts", "A.J. Brown", "D'Andre Swift", "DeVonta Smith"],
        "Giants": ["Daniel Jones", "Saquon Barkley", "Darius Slayton", "Darren Waller"],
    }

    nhl_players = {
        "Rangers": ["Artemi Panarin", "Mika Zibanejad", "Chris Kreider", "Adam Fox"],
        "Bruins": ["David Pastrnak", "Brad Marchand", "Charlie McAvoy", "Hampus Lindholm"],
        "Maple Leafs": ["Auston Matthews", "Mitch Marner", "William Nylander", "John Tavares"],
        "Avalanche": ["Nathan MacKinnon", "Mikko Rantanen", "Cale Makar", "Alexandar Georgiev"],
        "Golden Knights": ["Jack Eichel", "Mark Stone", "Jonathan Marchessault", "Shea Theodore"],
    }

    players_by_sport = {
        "basketball_nba": nba_players,
        "americanfootball_nfl": nfl_players,
        "icehockey_nhl": nhl_players,
    }

    player_map = players_by_sport.get(sport_key, nba_players)

    # Determine which teams and players to use
    if team and team in player_map:
        teams_to_use = [team]
    else:
        teams_to_use = list(player_map.keys())[:3]  # Use first 3 teams

    # Market-specific point ranges
    selected_markets = markets or ["player_points"]

    point_ranges = {
        "player_points": (20.5, 35.5) if sport_key == "basketball_nba" else (0.5, 3.5),
        "player_assists": (5.5, 12.5) if sport_key == "basketball_nba" else (0.5, 2.5),
        "player_rebounds": (8.5, 15.5),
        "player_threes": (2.5, 6.5),
        "player_rec_yds": (50.5, 120.5),
        "player_pass_yds": (200.5, 350.5),
        "player_rush_yds": (50.5, 120.5),
        "player_anytime_td": (0.5, 2.5),
        "player_pass_tds": (1.5, 3.5),
        "player_goals": (0.5, 1.5),
        "player_shots_on_goal": (2.0, 5.5),
        "player_power_play_points": (0.25, 1.5),
        "player_blocks": (1.5, 4.5),
        "player_saves": (24.5, 34.5),
    }

    default_range = (20.5, 35.5)

    now = datetime.now(timezone.utc)
    last_update = now.isoformat().replace("+00:00", "Z")
    events: List[Dict[str, Any]] = []
    for team_name in teams_to_use:
        players = player_map[team_name][:3]

        hours_ahead = random.randint(24, 168)
        commence_time = (now + timedelta(hours=hours_ahead)).isoformat().replace("+00:00", "Z")

        # Generate opponent team (simplified)
        opponent = random.choice([t for t in player_map.keys() if t != team_name])
        home_team = random.choice([team_name, opponent])
        away_team = opponent if home_team == team_name else team_name

        event_id = f"dummy_{sport_key}_{_slugify(away_team)}_at_{_slugify(home_team)}"

        def build_outcomes(market_key: str, *, over_price: int, under_price: int) -> Dict[str, Any]:
            market_range = point_ranges.get(market_key, default_range)
            outcomes: List[Dict[str, Any]] = []
            for player in players:
                point_value = round(random.uniform(market_range[0], market_range[1]) * 2) / 2
                outcomes.append({
                    "name": "Over",
                    "description": player,
                    "price": over_price,
                    "point": point_value,
                    "last_update": last_update,
                })
                outcomes.append({
                    "name": "Under",
                    "description": player,
                    "price": under_price,
                    "point": point_value,
                    "last_update": last_update,
                })

            return {
                "key": market_key,
                "outcomes": outcomes,
                "last_update": last_update,
            }

        bookmakers = []

        # Generate Novig odds first (best)
        for book_key in bookmaker_keys:
            if book_key.lower() == "novig":
                novig_markets = [
                    build_outcomes(market_key, over_price=-105, under_price=-105)
                    for market_key in selected_markets
                ]
                bookmakers.append({
                    "key": book_key,
                    "title": book_key.title(),
                    "markets": novig_markets,
                    "last_update": last_update,
                })
                break

        # Generate other books' odds (worse)
        for book_key in bookmaker_keys:
            if book_key.lower() == "novig":
                continue

            over_price = random.choice([-110, -115])
            under_price = random.choice([-110, -115])
            market_payloads = [
                build_outcomes(market_key, over_price=over_price, under_price=under_price)
                for market_key in selected_markets
            ]

            bookmakers.append({
                "key": book_key,
                "title": book_key.title(),
                "markets": market_payloads,
                "last_update": last_update,
            })

        events.append({
            "id": event_id,
            "sport_key": sport_key,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": commence_time,
            "bookmakers": bookmakers,
            "last_update": last_update,
        })

    return events

def find_best_comparison_outcome(
    *,
    outcomes: List[Dict[str, Any]],
    name: str,
    point: Optional[float],
    allow_half_point_flex: bool,
    opposite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the comparison book outcome that best matches a target book outcome.

    When ``opposite`` is True, search for an outcome with a different name (the
    other side of the bet). Preference is given to exact point matches, but for
    spreads/totals we will also accept lines that differ by up to 0.5.
    """

    best: Optional[Dict[str, Any]] = None
    best_diff: float = float("inf")

    for comp_outcome in outcomes:
        comp_name = comp_outcome.get("name")
        if opposite:
            if comp_name == name:
                continue
        elif comp_name != name:
            continue

        comp_point = comp_outcome.get("point", None)
        if not points_match(point, comp_point, allow_half_point_flex):
            continue

        diff = abs((point or 0.0) - (comp_point or 0.0))
        if diff < best_diff:
            best = comp_outcome
            best_diff = diff

            # Exact point match is the best we can do
            if diff < 1e-9:
                break

    return best


def normalize_player_name(value: str) -> str:
    """Normalize player names so books with punctuation or accents still match."""

    # Strip accents (e.g., "Gourde" vs "Gourdé") and non-alphanumeric characters
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


def collect_value_plays(
    events: List[Dict[str, Any]],
    market_key: str,
    target_book: str,
    compare_book: str,
) -> List[ValuePlayOutcome]:
    """
    Scan all events and outcomes in the given market, comparing target_book vs compare_book.
    Only considers outcomes where:
      - both books have a price,
      - and for spreads/totals/props, the points match (within 0.5 for spreads/totals).

    Also:
      - Finds the *other* comparison book outcome (matching or close point, different name)
        and exposes its true odds + team name as "novig_reverse_*" (hedge side).
      - Detects 2-way arbitrage: back this side at the target book, back the
        opposite side at the comparison book.
    """
    plays: List[ValuePlayOutcome] = []

    # Filter out live events at the event level
    now_utc = datetime.now(timezone.utc)

    is_player_prop = market_key.startswith("player_")
    is_totals_market = market_key == "totals"

    def _sanitize_outcomes(market: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return a filtered list of usable outcomes for comparisons."""

        cleaned: List[Dict[str, Any]] = []
        for outcome in market.get("outcomes", []):
            name = outcome.get("name")
            price = sanitize_american_price(outcome.get("price"))
            point = outcome.get("point", None)
            description = outcome.get("description", None)

            if name is None or price is None:
                continue

            if is_totals_market:
                if point is None:
                    continue
                if name.lower() not in ("over", "under"):
                    continue
                if price < -150 or price > 150:
                    continue

            cleaned.append(
                {
                    "name": name,
                    "price": price,
                    "point": point,
                    "description": description,
                }
            )

        return cleaned

    def _find_matching_outcome(
        outcomes: List[Dict[str, Any]],
        expected_name: str,
        expected_description: Optional[str],
        expected_point: Optional[float],
        *,
        allow_half_point_flex: bool,
        opposite: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Find the best matching outcome for a selection, favoring player/point matches.

        For player props we prioritize exact player matches. If multiple players share the
        same line, we avoid returning a mismatched player by requiring the description to
        align when provided. Only when a single candidate fits the line do we fall back to
        a point-based match without a description.
        """

        if is_player_prop:
            normalized_desc = (
                normalize_player_name(expected_description)
                if expected_description
                else None
            )

            candidates: List[Dict[str, Any]] = []
            for comp_outcome in outcomes:
                comp_name = comp_outcome.get("name")
                if opposite:
                    if comp_name == expected_name:
                        continue
                elif comp_name != expected_name:
                    continue

                comp_point = comp_outcome.get("point", None)
                if not points_match(expected_point, comp_point, allow_half_point_flex):
                    continue

                candidates.append(comp_outcome)

            if normalized_desc:
                for comp_outcome in candidates:
                    comp_desc = comp_outcome.get("description")
                    if comp_desc and normalized_desc == normalize_player_name(comp_desc):
                        return comp_outcome

                described_candidates = [c for c in candidates if c.get("description")]
                if described_candidates:
                    # We have player-labeled outcomes but none match the requested player;
                    # avoid pairing with the wrong athlete.
                    return None

            if len(candidates) == 1:
                return candidates[0]

            return None

        return find_best_comparison_outcome(
            outcomes=outcomes,
            name=expected_name,
            point=expected_point,
            allow_half_point_flex=allow_half_point_flex,
            opposite=opposite,
        )
    
    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        # Skip events that have already started (live or completed)
        if start_time:
            try:
                event_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                if event_dt <= now_utc:
                    # Event has started or is live, skip it
                    continue
            except Exception:
                # If we can't parse the time, skip to be safe
                continue
        else:
            # No start time, skip to be safe
            continue

        matchup = f"{away} @ {home}" if home and away else ""

        compare_market = None
        book_market = None
        market_outcomes_by_book: Dict[str, List[Dict[str, Any]]] = {}

        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            sanitized_outcomes = _sanitize_outcomes(market)
            if not sanitized_outcomes:
                continue

            market_outcomes_by_book[key] = sanitized_outcomes

            if key == compare_book:
                compare_market = market
            elif key == target_book:
                book_market = market

        if not compare_market or not book_market:
            continue

        # For moneylines, only process events where the target book has posted both sides.
        # This avoids calculating synthetic prices when the sportsbook has not actually
        # published the moneyline market yet.
        book_outcomes = market_outcomes_by_book.get(target_book, [])
        if market_key == "h2h":
            posted_prices = [
                sanitized_price
                for o in book_outcomes
                for sanitized_price in [sanitize_american_price(o.get("price"))]
                if sanitized_price is not None
            ]
            if len(posted_prices) < 2:
                continue

        # Allow 0.5-point flex for spreads, totals, and player props (Odds API sometimes
        # differs by 0.5 between books).
        allow_half_point_flex = market_key in ("totals", "spreads") or is_player_prop
        compare_outcomes: List[Dict[str, Any]] = market_outcomes_by_book.get(compare_book, [])
        if not compare_outcomes:
            continue

        def _collect_prices_for_selection(
            outcome_name: str, outcome_description: Optional[str], outcome_point: Optional[float]
        ) -> Dict[str, Optional[int]]:
            prices: Dict[str, Optional[int]] = {}
            for book_key, outcomes in market_outcomes_by_book.items():
                match = _find_matching_outcome(
                    outcomes,
                    expected_name=outcome_name,
                    expected_description=outcome_description,
                    expected_point=outcome_point,
                    allow_half_point_flex=allow_half_point_flex,
                )
                prices[book_key] = match.get("price") if match and match.get("price") is not None else None
            return prices

        for o in book_outcomes:
            name = o.get("name")
            price = sanitize_american_price(o.get("price"))
            point = o.get("point", None)
            description = o.get("description", None)  # For player props, this is the player name
            if name is None or price is None:
                continue

            # For totals markets, outcomes MUST have a point value (totals always have a line)
            # Also validate that the name is "Over" or "Under" for totals
            # Totals odds should be in a reasonable range (typically -150 to +150, not like -300 which is ML territory)
            if market_key == "totals":
                if point is None:
                    continue
                if name.lower() not in ("over", "under"):
                    continue  # Skip invalid totals outcomes
                # Skip totals with extreme prices that look like moneyline odds (e.g., -300, +400)
                # Totals typically range from -150 to +150
                if price is not None and (price < -150 or price > 150):
                    continue  # Skip suspiciously extreme totals prices

            if market_key in ("totals", "spreads"):
                # For spreads/totals, use the raw book price to avoid inflating lines like
                # -110 to unrealistic values (e.g., -300) after vig adjustments.
                adjusted_price = price
                adjusted_price = max(-150, min(150, adjusted_price))
            elif is_player_prop:
                # For player props, keep the raw price so we display the true odds
                # from the sportsbook instead of an exaggerated vig-adjusted number.
                adjusted_price = price
            else:
                # Apply vig adjustment to target book odds (makes them less favorable)
                adjusted_price = apply_vig_adjustment(price, target_book)

            # For player props, match by name, description (player), and point
            matching_compare = _find_matching_outcome(
                compare_outcomes,
                expected_name=name,
                expected_description=description,
                expected_point=point,
                allow_half_point_flex=allow_half_point_flex,
            )
            if matching_compare is None:
                continue
            # For spreads/totals arbitrage comparisons, require the exact same point line
            if market_key in ("totals", "spreads") and not points_match(
                point, matching_compare.get("point"), allow_half_point_flex=False
            ):
                continue

            # Find the *other* comparison book side (hedge side) with matching/close point
            other_compare = None
            if is_player_prop and description:
                # For player props, find opposite side (Over -> Under or vice versa) with same player and point
                opposite_name = "Under" if name == "Over" else "Over"
                other_compare = _find_matching_outcome(
                    compare_outcomes,
                    expected_name=opposite_name,
                    expected_description=description,
                    expected_point=point,
                    allow_half_point_flex=allow_half_point_flex,
                )
            else:
                other_compare = _find_matching_outcome(
                    compare_outcomes,
                    expected_name=name,
                    expected_description=description,
                    expected_point=point,
                    allow_half_point_flex=allow_half_point_flex,
                    opposite=True,
                )
            if market_key in ("totals", "spreads") and other_compare is not None:
                # Require the hedge side to share the same point to avoid mismatched lines
                if not points_match(point, other_compare.get("point"), allow_half_point_flex=False):
                    other_compare = None

            # Require an opposite-side price so we only surface hedgeable bets
            if other_compare is None or other_compare.get("price") is None:
                continue

            compare_price = matching_compare.get("price")
            if compare_price is None:
                continue

            ev_pct = estimate_ev_percent(book_odds=adjusted_price, sharp_odds=compare_price)

            novig_reverse_name: Optional[str] = None
            novig_reverse_price: Optional[int] = None
            hedge_ev_percent: Optional[float] = None
            is_arb = False
            arb_margin_percent: Optional[float] = None

            if other_compare is not None:
                novig_reverse_name = other_compare.get("name")
                novig_reverse_price = other_compare.get("price")

                # 2-way arb math:
                #  - back this side at target_book (book_price with vig adjustment)
                #  - back opposite side at comparison book (novig_reverse_price)
                d_book = american_to_decimal(adjusted_price)
                d_compare_other = american_to_decimal(novig_reverse_price)
                inv_sum = 1.0 / d_book + 1.0 / d_compare_other
                # Hedge margin: 0% ~ fair (e.g. -125 / +125), >0% profitable arb, <0% losing hedge
                # Add a small buffer (0.001 = 0.1%) to prevent exactly 0% margins from showing
                # This ensures arbitrage opportunities are truly rare
                arb_margin_percent = (1.0 - inv_sum) * 100.0 - 0.1
                hedge_ev_percent = arb_margin_percent
                if arb_margin_percent > 0:
                    is_arb = True


            # For player props, include player name and line in outcome_name
            outcome_display_name = name
            player_prop_units = {
                "player_points": "points",
                "player_assists": "assists",
                "player_rebounds": "rebounds",
                "player_threes": "3-pointers",
                "player_rec_yds": "receiving yards",
                "player_pass_yds": "passing yards",
                "player_rush_yds": "rushing yards",
                "player_anytime_td": "touchdowns",
                "player_pass_tds": "passing TDs",
                "player_goals": "goals",
                "player_shots_on_goal": "shots on goal",
                "player_power_play_points": "power play points",
                "player_blocks": "blocks",
                "player_saves": "saves",
            }
            if is_player_prop and description:
                line_suffix = ""
                if point is not None:
                    stat_unit = player_prop_units.get(market_key, "")
                    stat_label = f" {stat_unit}" if stat_unit else ""
                    line_suffix = f" {point}{stat_label}"
                outcome_display_name = f"{description} {name}{line_suffix}"
            # For totals, include the point value in outcome_name (e.g., "Over 225.5")
            elif market_key == "totals" and point is not None:
                outcome_display_name = f"{name} {point}"
            
            reverse_display_name = novig_reverse_name
            if is_player_prop and other_compare and other_compare.get("description"):
                reverse_desc = other_compare.get("description")
                reverse_line_suffix = ""
                if point is not None:
                    stat_unit = player_prop_units.get(market_key, "")
                    stat_label = f" {stat_unit}" if stat_unit else ""
                    reverse_line_suffix = f" {point}{stat_label}"
                reverse_display_name = (
                    f"{reverse_desc} {novig_reverse_name}{reverse_line_suffix}"
                    if novig_reverse_name
                    else None
                )
            # For totals, include the point value in reverse outcome_name
            elif market_key == "totals" and novig_reverse_name and point is not None:
                reverse_display_name = f"{novig_reverse_name} {point}"

            book_prices = _collect_prices_for_selection(name, description, point)
            hedge_prices: Dict[str, Optional[int]] = {}
            if other_compare is not None:
                hedge_prices = _collect_prices_for_selection(
                    other_compare.get("name", novig_reverse_name or ""),
                    other_compare.get("description", description),
                    other_compare.get("point", point),
                )

            plays.append(
                ValuePlayOutcome(
                    event_id=event_id,
                    matchup=matchup,
                    start_time=start_time,
                    outcome_name=outcome_display_name,
                    point=point,
                    market=market_key,
                    novig_price=compare_price,
                    novig_reverse_name=reverse_display_name,
                    novig_reverse_price=novig_reverse_price,
                    book_price=adjusted_price,  # Use adjusted price with vig
                    book_prices=book_prices,
                    opposing_prices=hedge_prices,
                    ev_percent=ev_pct,
                    hedge_ev_percent=hedge_ev_percent,
                    is_arbitrage=is_arb,
                    arb_margin_percent=arb_margin_percent,
                )
            )

    return plays
# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------

app = FastAPI()


def _require_dummy_data_allowed(requested: bool) -> bool:
    """Return True when dummy data is requested and startup allows it."""

    if DUMMY_DATA_ENABLED and not os.getenv("PYTEST_CURRENT_TEST"):
        return True

    if not requested:
        return False

    allow_test_override = os.getenv("ALLOW_DUMMY_DATA_FOR_TESTS", "")
    if allow_test_override.lower() in {"1", "true", "yes"} or os.getenv(
        "PYTEST_CURRENT_TEST", ""
    ):
        logger.warning(
            "Allowing dummy data because ALLOW_DUMMY_DATA_FOR_TESTS is enabled"
        )
        return True

    raise HTTPException(
        status_code=403,
        detail=(
            "Dummy data is disabled. Restart the server with -DummyData to enable "
            "mock odds."
        ),
    )


def _validate_data_source(events: List[Dict[str, Any]], allow_dummy: bool) -> None:
    """Ensure dummy payloads never leak into live calls unexpectedly."""

    if allow_dummy:
        return

    dummy_events = [e for e in events if str(e.get("id", "")).startswith("dummy_")]
    if dummy_events:
        logger.error("Dummy data returned while disabled: ids=%s", [e.get("id") for e in dummy_events])
        raise HTTPException(
            status_code=502,
            detail="Received placeholder odds while live data is required",
        )


# Repository and service instances
odds_repository = OddsRepository(
    api_key_provider=get_api_key,
    odds_fetcher=fetch_odds,
    player_props_fetcher=fetch_player_props,
    events_fetcher=fetch_sport_events,
    dummy_odds_generator=generate_dummy_odds_data,
    dummy_player_props_generator=generate_dummy_player_props_data,
)


def _sync_repository_sources() -> None:
    updated = False

    if odds_repository._api_key_provider is not get_api_key:
        odds_repository._api_key_provider = get_api_key
        updated = True
    if odds_repository._odds_fetcher is not fetch_odds:
        odds_repository._odds_fetcher = fetch_odds
        updated = True
    if odds_repository._player_props_fetcher is not fetch_player_props:
        odds_repository._player_props_fetcher = fetch_player_props
        updated = True
    if odds_repository._events_fetcher is not fetch_sport_events:
        odds_repository._events_fetcher = fetch_sport_events
        updated = True
    if odds_repository._dummy_odds_generator is not generate_dummy_odds_data:
        odds_repository._dummy_odds_generator = generate_dummy_odds_data
        updated = True
    if odds_repository._dummy_player_props_generator is not generate_dummy_player_props_data:
        odds_repository._dummy_player_props_generator = generate_dummy_player_props_data
        updated = True

    if updated:
        odds_repository._cache.clear()


def _resolve_api_key(use_dummy_data: bool) -> str:
    """Return an API key unless dummy data is requested."""

    _sync_repository_sources()

    try:
        return odds_repository.resolve_api_key(use_dummy_data)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Service instances
odds_service = OddsService(
    repository=odds_repository,
    data_validator=_validate_data_source,
)

value_play_service = ValuePlayService(
    repository=odds_repository,
    data_validator=_validate_data_source,
    collect_value_plays=collect_value_plays,
)


def _load_sports_schema() -> list:
    schema_path = Path(__file__).parent / "data" / "sports_schema.json"
    if not schema_path.exists():
        return []
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            return []
        return payload
    except Exception:
        logger.exception("Failed to read sports schema")
        return []


@app.get("/api/sports")
def get_sports_schema():
    """Return the sports schema JSON used to drive frontend sport selectors.

    Reads `data/sports_schema.json` from the project root and returns the
    parsed content. Returns 404 if missing or 500 on parse errors.
    """
    payload = _load_sports_schema()
    if not payload:
        raise HTTPException(status_code=404, detail="Sports schema not found or invalid")
    # Basic validation: expect a list of objects with a 'key' field
    for item in payload:
        if not isinstance(item, dict) or "key" not in item:
            raise HTTPException(status_code=500, detail="Sports schema malformed")
    return payload


@app.post("/api/odds", response_model=OddsResponse)
def get_odds(payload: OddsRequest) -> OddsResponse:
    """
    Odds endpoint used by the watcher UI: returns current prices and best line
    for specific teams/bets the user is tracking.
    """
    if not payload.bets:
        raise HTTPException(status_code=400, detail="No bets provided")

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    api_key = _resolve_api_key(use_dummy_data)

    all_book_keys: Set[str] = set()
    for bet in payload.bets:
        all_book_keys.update(bet.bookmaker_keys)

    if not all_book_keys:
        raise HTTPException(status_code=400, detail="No bookmakers specified")

    domain_bets = domain_mappers.map_bet_requests_to_domain(payload.bets)
    odds_result = odds_service.get_odds(
        bets=domain_bets, api_key=api_key, use_dummy_data=use_dummy_data
    )

    return domain_mappers.map_odds_result_to_dto(
        odds_result,
        price_out_model=PriceOut,
        single_bet_odds_model=SingleBetOdds,
        odds_response_model=OddsResponse,
    )


@app.post("/api/value-plays", response_model=ValuePlaysResponse)
def get_value_plays(payload: ValuePlaysRequest) -> ValuePlaysResponse:
    """
    Compare a target sportsbook to a comparison book for a given sport
    and market, returning the best value plays.

    Sorting:
      - Primary sort is by hedge opportunity using arb_margin_percent:
          arb_margin_percent = (1 - (1/dec_book + 1/dec_compare_opposite)) * 100
        where dec_book is the decimal odds at the target book, and
        dec_compare_opposite is the decimal odds of the comparison book *opposite* side.
      - A pair like -125 / +125 gives ~0% (fair hedge).
      - Positive values indicate 2-way arbitrage (profitable hedge),
        negative values indicate a losing hedge.
      - Plays with no comparison book opposite side are pushed to the bottom.
    """
    target_book = payload.target_book
    compare_book = payload.compare_book
    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    api_key = _resolve_api_key(use_dummy_data)

    domain_request = domain_mappers.map_value_plays_query(payload)
    domain_result = value_play_service.get_value_plays(
        payload=domain_request, api_key=api_key, use_dummy_data=use_dummy_data
    )

    return domain_mappers.map_value_plays_result_to_dto(
        domain_result,
        value_play_model=ValuePlayOutcome,
        response_model=ValuePlaysResponse,
    )


@app.post("/api/best-value-plays", response_model=BestValuePlaysResponse)
def get_best_value_plays(payload: BestValuePlaysRequest) -> BestValuePlaysResponse:
    """
    Search across multiple sports and markets to find the best +EV bets by hedge odds.
    Returns the top value plays sorted by arb_margin_percent (hedge opportunity).
    """
    target_book = payload.target_book
    compare_book = payload.compare_book

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    if not payload.sport_keys or not payload.markets:
        raise HTTPException(
            status_code=400,
            detail="At least one sport and one market must be specified.",
        )

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    api_key = _resolve_api_key(use_dummy_data)

    domain_payload = domain_mappers.map_best_value_plays_query(payload)
    domain_result = value_play_service.get_best_value_plays(
        payload=domain_payload, api_key=api_key, use_dummy_data=use_dummy_data
    )

    return domain_mappers.map_best_value_plays_result_to_dto(
        domain_result,
        best_value_model=BestValuePlayOutcome,
        response_model=BestValuePlaysResponse,
    )


def _clamp_boost_percent(boost_percent: Optional[float]) -> float:
    if boost_percent is None:
        return 30.0
    return max(20.0, min(100.0, boost_percent))


def _combine_leg_odds(legs: List[ValuePlayOutcome]) -> tuple[Optional[float], Optional[int]]:
    if not legs:
        return None, None

    combined_decimal = 1.0
    for leg in legs:
        try:
            combined_decimal *= american_to_decimal(leg.book_price)
        except Exception:
            return None, None

    american = decimal_to_american(combined_decimal)
    return combined_decimal, american


def _apply_boost(decimal_odds: Optional[float], boost_percent: float) -> tuple[Optional[float], Optional[int]]:
    if decimal_odds is None:
        return None, None
    boosted_decimal = decimal_odds * (1.0 + boost_percent / 100.0)
    boosted_american = decimal_to_american(boosted_decimal)
    return boosted_decimal, boosted_american


def _hedge_value(play: ValuePlayOutcome) -> float:
    if play.arb_margin_percent is not None:
        return play.arb_margin_percent
    if play.hedge_ev_percent is not None:
        return play.hedge_ev_percent
    return play.ev_percent


def _select_top_parlay_legs(
    plays: List[BestValuePlayOutcome], desired_legs: int
) -> List[BestValuePlayOutcome]:
    sorted_plays = sorted(plays, key=_hedge_value, reverse=True)
    legs: List[BestValuePlayOutcome] = []
    seen_events: Set[str] = set()

    for play in sorted_plays:
        if play.event_id in seen_events:
            continue
        legs.append(play)
        seen_events.add(play.event_id)
        if len(legs) >= desired_legs:
            break

    return legs


@app.post("/api/parlay-builder", response_model=ParlayBuilderResponse)
def build_best_parlay(payload: ParlayBuilderRequest) -> ParlayBuilderResponse:
    """Build a high-value parlay using the best hedge EV plays across sports/markets."""

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    boost_percent = _clamp_boost_percent(payload.boost_percent)
    # Request extra results to increase the chance of filling out the parlay.
    desired_results = max(payload.max_results or 50, payload.parlay_size * 4)
    best_request = BestValuePlaysRequest(
        sport_keys=payload.sport_keys,
        markets=payload.markets,
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        max_results=desired_results,
        use_dummy_data=use_dummy_data,
    )

    best_response = get_best_value_plays(best_request)
    legs = _select_top_parlay_legs(best_response.plays, payload.parlay_size)
    notes: List[str] = []

    if use_dummy_data:
        notes.append("Using dummy odds data for development; prices are sample values and not live lines.")

    if not legs:
        notes.append("No eligible legs found for the requested parlay size.")
        combined_decimal = None
        combined_american = None
    else:
        combined_decimal, combined_american = _combine_leg_odds(legs)
        if len(legs) < payload.parlay_size:
            notes.append(
                f"Only {len(legs)} legs available based on current odds and filters."
            )

    boosted_decimal, boosted_american = _apply_boost(combined_decimal, boost_percent)

    return ParlayBuilderResponse(
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        parlay_legs=legs,
        combined_decimal_odds=combined_decimal,
        combined_american_odds=combined_american,
        boost_percent=boost_percent,
        boosted_decimal_odds=boosted_decimal,
        boosted_american_odds=boosted_american,
        notes=notes,
        used_dummy_data=use_dummy_data,
    )


def _extract_player_name(outcome_name: str) -> Optional[str]:
    if not outcome_name:
        return None
    lowered = outcome_name.lower()
    for keyword in [" over", " under"]:
        idx = lowered.find(keyword)
        if idx > 0:
            return outcome_name[:idx].strip()
    return outcome_name.strip()


def _select_uncorrelated_legs(
    plays: List[ValuePlayOutcome],
    max_legs: int,
    avoid_correlation: bool = True,
) -> List[ValuePlayOutcome]:
    sorted_plays = sorted(plays, key=_hedge_value, reverse=True)
    legs: List[ValuePlayOutcome] = []
    used_players: Set[str] = set()
    used_markets: Set[str] = set()

    for play in sorted_plays:
        player_name = _extract_player_name(play.outcome_name)
        if avoid_correlation:
            if play.market and play.market in used_markets:
                continue
            if player_name and player_name.lower() in used_players:
                continue

        legs.append(play)
        if play.market:
            used_markets.add(play.market)
        if player_name:
            used_players.add(player_name.lower())

        if len(legs) >= max_legs:
            break

    return legs


def _build_sgp_suggestion(
    legs: List[ValuePlayOutcome],
    boost_percent: float,
    note: Optional[str] = None,
) -> SGPSuggestion:
    combined_decimal, combined_american = _combine_leg_odds(legs)
    boosted_decimal, boosted_american = _apply_boost(combined_decimal, boost_percent)
    first_leg = legs[0]
    return SGPSuggestion(
        event_id=first_leg.event_id,
        matchup=first_leg.matchup,
        start_time=first_leg.start_time,
        legs=legs,
        combined_decimal_odds=combined_decimal,
        combined_american_odds=combined_american,
        boost_percent=boost_percent,
        boosted_decimal_odds=boosted_decimal,
        boosted_american_odds=boosted_american,
        note=note,
    )


def _sgp_score(legs: List[ValuePlayOutcome]) -> float:
    return sum(_hedge_value(leg) for leg in legs)


def _total_american_odds(sgp: SGPSuggestion) -> Optional[int]:
    if sgp.boosted_american_odds is not None:
        return sgp.boosted_american_odds
    return sgp.combined_american_odds


def _sgp_within_odds_range(
    sgp: SGPSuggestion, min_total: int, max_total: int
) -> bool:
    total_american = _total_american_odds(sgp)
    if total_american is None:
        return False
    return min_total <= total_american <= max_total


@app.post("/api/sgp-builder", response_model=SGPBuilderResponse)
def build_sgp(payload: SGPBuilderRequest) -> SGPBuilderResponse:
    """Recommend SGP legs by picking the best player props within a single game."""

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    boost_percent = _clamp_boost_percent(payload.boost_percent)
    warnings: List[str] = []
    min_total_odds = payload.min_total_american_odds or 100
    max_total_odds = payload.max_total_american_odds or 20000

    if min_total_odds > max_total_odds:
        min_total_odds, max_total_odds = max_total_odds, min_total_odds
        warnings.append(
            "Swapped min/max total odds because the minimum exceeded the maximum."
        )

    # Pull all supported player prop markets for the selected sport.
    markets = PlayerPropsRequest.PLAYER_PROP_MARKETS_BY_SPORT.get(
        payload.sport_key, PlayerPropsRequest.ALL_PLAYER_PROP_MARKETS
    )

    props_request = PlayerPropsRequest(
        sport_key=payload.sport_key,
        team=None,
        player_name=None,
        event_id=payload.event_id,
        markets=markets,
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        use_dummy_data=use_dummy_data,
    )

    props_response = get_player_props(props_request)

    if not props_response.plays:
        warnings.append("No player props available to build an SGP right now.")
        return SGPBuilderResponse(
            sport_key=payload.sport_key,
            target_book=payload.target_book,
            compare_book=payload.compare_book,
            warnings=warnings,
        )

    plays_by_event: Dict[str, List[ValuePlayOutcome]] = {}
    for play in props_response.plays:
        plays_by_event.setdefault(play.event_id, []).append(play)

        if payload.event_id and payload.event_id not in plays_by_event:
            warnings.append("No player props found for the selected game.")
            return SGPBuilderResponse(
                sport_key=payload.sport_key,
                target_book=payload.target_book,
                compare_book=payload.compare_book,
                warnings=warnings,
            )

    best_sgp: Optional[SGPSuggestion] = None
    uncorrelated_sgp: Optional[SGPSuggestion] = None
    best_sgp_score: float = float("-inf")
    uncorrelated_score: float = float("-inf")

    filtered_outside_range = 0

    for event_id, plays in plays_by_event.items():
        if not plays:
            continue

        sorted_plays = sorted(plays, key=_hedge_value, reverse=True)
        top_three = sorted_plays[:3]
        if len(top_three) < 2:
            continue

        candidate_best = _build_sgp_suggestion(top_three, boost_percent)
        if _sgp_within_odds_range(candidate_best, min_total_odds, max_total_odds):
            candidate_score = _sgp_score(top_three)
            if candidate_score > best_sgp_score:
                best_sgp = candidate_best
                best_sgp_score = candidate_score
        else:
            filtered_outside_range += 1

        if payload.avoid_correlation:
            unique_legs = _select_uncorrelated_legs(plays, max_legs=3, avoid_correlation=True)
            if len(unique_legs) >= 2:
                candidate_uncorrelated = _build_sgp_suggestion(
                    unique_legs,
                    boost_percent,
                    note="Uncorrelated SGP to reduce vig risk.",
                )
                if _sgp_within_odds_range(
                    candidate_uncorrelated, min_total_odds, max_total_odds
                ):
                    candidate_score = _sgp_score(unique_legs)
                    if candidate_score > uncorrelated_score:
                        uncorrelated_sgp = candidate_uncorrelated
                        uncorrelated_score = candidate_score
                else:
                    filtered_outside_range += 1

    if best_sgp and len(best_sgp.legs) < 3:
        warnings.append(
            "Found a same-game parlay but fewer than 3 high-value props were available."
        )

    if payload.avoid_correlation and best_sgp and uncorrelated_sgp is None:
        warnings.append(
            "Could not find an uncorrelated set of props; showing the best available mix instead."
        )

    if filtered_outside_range:
        warnings.append(
            f"Skipped {filtered_outside_range} SGP option(s) outside the odds range "
            f"{decimal_to_american(american_to_decimal(min_total_odds)) if min_total_odds else min_total_odds} "
            f"to {decimal_to_american(american_to_decimal(max_total_odds)) if max_total_odds else max_total_odds}."
        )

    return SGPBuilderResponse(
        sport_key=payload.sport_key,
        target_book=payload.target_book,
        compare_book=payload.compare_book,
        best_sgp=best_sgp,
        uncorrelated_sgp=uncorrelated_sgp,
        warnings=warnings,
    )


def _filter_upcoming_events_only(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return events that have not started yet."""

    def _parse_timestamp(raw_value: Optional[str]) -> Optional[datetime]:
        if not raw_value:
            return None

        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except Exception:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    upcoming: List[Dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    for event in events:
        event_dt = _parse_timestamp(event.get("commence_time"))
        if event_dt and event_dt > now_utc:
            upcoming.append(event)

    return upcoming


def _extract_latest_update_timestamp(events: List[Dict[str, Any]]) -> Optional[str]:
    """Return the most recent ``last_update`` timestamp from event payloads."""

    def _coerce(raw_value: Optional[str]) -> Optional[datetime]:
        if not raw_value:
            return None

        try:
            dt = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except Exception:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    latest: Optional[datetime] = None

    for event in events:
        for candidate in (
            event.get("last_update"),
            *(bookmaker.get("last_update") for bookmaker in event.get("bookmakers", [])),
        ):
            ts = _coerce(candidate)
            if ts and (latest is None or ts > latest):
                latest = ts

        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                ts = _coerce(market.get("last_update"))
                if ts and (latest is None or ts > latest):
                    latest = ts

                for outcome in market.get("outcomes", []):
                    ts = _coerce(outcome.get("last_update"))
                    if ts and (latest is None or ts > latest):
                        latest = ts

    if latest is None:
        return None

    return latest.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _collect_main_markets(event: Dict[str, Any]) -> set[str]:
    markets: set[str] = set()

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            key = market.get("key")
            if key in FEATURED_MARKETS:
                markets.add(key)

    return markets


def _featured_game_score(event: Dict[str, Any]) -> float:
    """Weight games by available markets and proximity to start time."""

    markets_seen = _collect_main_markets(event)
    market_score = len(markets_seen) * 2

    commence_time = event.get("commence_time")
    recency_score = 0.0
    if commence_time:
        try:
            event_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            hours_until = (event_dt - datetime.now(timezone.utc)).total_seconds() / 3600
            if 0 <= hours_until <= FEATURED_LOOKAHEAD_HOURS:
                recency_score = (FEATURED_LOOKAHEAD_HOURS - hours_until) / FEATURED_LOOKAHEAD_HOURS
        except Exception:
            pass

    matchup_bonus = 0.5 if event.get("home_team") and event.get("away_team") else 0.0
    return market_score + recency_score + matchup_bonus


def _matchup_label(event: Dict[str, Any]) -> str:
    home = event.get("home_team", "Home")
    away = event.get("away_team", "Away")
    return f"{away} @ {home}"


def _within_featured_window(event: Dict[str, Any]) -> bool:
    commence_time = event.get("commence_time")
    if not commence_time:
        return False

    try:
        event_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    except Exception:
        return False

    now_utc = datetime.now(timezone.utc)
    hours_until = (event_dt - now_utc).total_seconds() / 3600
    return 0 <= hours_until <= FEATURED_LOOKAHEAD_HOURS


@app.get("/api/featured-games", response_model=FeaturedGamesResponse)
def list_featured_games(use_dummy_data: bool = False) -> FeaturedGamesResponse:
    """Return a ranked list of upcoming headline games for SGP building."""

    use_dummy_data = _require_dummy_data_allowed(use_dummy_data)

    bookmaker_keys = ["draftkings", "fanduel", "novig"]

    api_key = _resolve_api_key(use_dummy_data)

    games: List[FeaturedGame] = []
    seen_ids: set[str] = set()

    for sport_key in FEATURED_SPORTS:
        try:
            events = odds_repository.get_odds_events(
                api_key=api_key,
                sport_key=sport_key,
                markets=FEATURED_MARKETS,
                bookmaker_keys=bookmaker_keys,
                use_dummy_data=use_dummy_data,
            )
        except HTTPException as exc:
            logger.warning(
                "Skipping featured games for sport=%s: %s", sport_key, exc.detail
            )
            continue

        _validate_data_source(events, allow_dummy=use_dummy_data)

        for event in _filter_upcoming_events_only(events):
            if not _within_featured_window(event):
                continue

            event_id = event.get("id")
            if not event_id or event_id in seen_ids:
                continue

            games.append(
                FeaturedGame(
                    sport_key=sport_key,
                    event_id=event_id,
                    matchup=_matchup_label(event),
                    commence_time=event.get("commence_time"),
                    popularity_score=_featured_game_score(event),
                    available_markets=sorted(_collect_main_markets(event)),
                )
            )
            seen_ids.add(event_id)

    games.sort(key=lambda g: (-g.popularity_score, g.commence_time or ""))

    return FeaturedGamesResponse(games=games, used_dummy_data=use_dummy_data)


def collect_available_player_prop_markets(
    events_payload: List[Dict[str, Any]],
    target_book: Optional[str],
    compare_book: Optional[str],
) -> tuple[set[str], set[str]]:
    """
    Return a tuple of (all_markets_seen, markets_available_for_both_books).
    The second set only includes markets where both the target and comparison
    books have prices in at least one event.
    """

    all_seen: set[str] = set()
    comparable: set[str] = set()

    for event in events_payload:
        target_markets: set[str] = set()
        compare_markets: set[str] = set()
        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key")
            market_keys = {
                m.get("key")
                for m in bookmaker.get("markets", [])
                if m.get("key")
            }
            all_seen.update(market_keys)

            if target_book and book_key == target_book:
                target_markets.update(market_keys)
            if compare_book and book_key == compare_book:
                compare_markets.update(market_keys)

        if target_book and compare_book:
            comparable.update(target_markets & compare_markets)

    return all_seen, comparable


@app.post("/api/player-props/games", response_model=PlayerPropGamesResponse)
def list_player_prop_games(payload: PlayerPropGamesRequest) -> PlayerPropGamesResponse:
    """Provide a list of upcoming games that have player props."""

    # Validate sport key against local schema to avoid calling the remote API
    schema = _load_sports_schema()
    available_keys = {item.get('key') for item in schema if isinstance(item, dict) and item.get('key')}
    if payload.sport_key not in available_keys:
        raise HTTPException(status_code=400, detail=f"Unknown sport key: {payload.sport_key}. See /api/sports for available keys.")

    ensure_player_props_supported(payload.sport_key)

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    discovery_markets = PlayerPropsRequest.PLAYER_PROP_MARKETS_BY_SPORT.get(
        payload.sport_key, PlayerPropsRequest.ALL_PLAYER_PROP_MARKETS
    )

    api_key = _resolve_api_key(use_dummy_data)

    try:
        events = odds_repository.get_sport_events(
            api_key=api_key,
            sport_key=payload.sport_key,
            use_dummy_data=use_dummy_data,
            discovery_markets=discovery_markets,
            bookmaker_keys=["novig", "draftkings", "fanduel"],
        )
    except HTTPException as exc:
        logger.error("Events API error for sport=%s: %s", payload.sport_key, exc.detail)
        raise HTTPException(
            status_code=502,
            detail=f"Events API error for sport {payload.sport_key}: {exc.detail}",
        )

    _validate_data_source(events, allow_dummy=use_dummy_data)

    events = _filter_upcoming_events_only(events)

    last_update = _extract_latest_update_timestamp(events)

    games: List[PlayerPropEvent] = []
    for event in events:
        event_id = event.get("id")
        home = event.get("home_team")
        away = event.get("away_team")
        if not event_id or not home or not away:
            continue

        games.append(
            PlayerPropEvent(
                event_id=event_id,
                matchup=f"{away} @ {home}",
                commence_time=event.get("commence_time"),
            )
        )

    games.sort(key=lambda g: g.commence_time or "")

    return PlayerPropGamesResponse(
        sport_key=payload.sport_key, games=games, last_update=last_update
    )


@app.post("/api/player-props/markets", response_model=PlayerPropMarketsResponse)
def list_player_prop_markets(
    payload: PlayerPropMarketsRequest,
) -> PlayerPropMarketsResponse:
    """Discover available player prop markets for a sport."""

    # Validate sport key against local schema
    schema = _load_sports_schema()
    available_keys = {item.get('key') for item in schema if isinstance(item, dict) and item.get('key')}
    if payload.sport_key not in available_keys:
        raise HTTPException(status_code=400, detail=f"Unknown sport key: {payload.sport_key}. See /api/sports for available keys.")

    ensure_player_props_supported(payload.sport_key)

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)

    discovery_markets = PlayerPropsRequest.PLAYER_PROP_MARKETS_BY_SPORT.get(
        payload.sport_key, PlayerPropsRequest.ALL_PLAYER_PROP_MARKETS
    )

    bookmaker_keys = [
        book
        for book in (payload.target_book, payload.compare_book)
        if book is not None
    ]
    if not bookmaker_keys:
        bookmaker_keys = ["novig", "draftkings"]

    api_key = _resolve_api_key(use_dummy_data)

    try:
        events = odds_repository.get_odds_events(
            api_key=api_key,
            sport_key=payload.sport_key,
            markets=discovery_markets,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=use_dummy_data,
            force_player_props=True,
        )
    except HTTPException as exc:
        logger.error("Player props API error for sport=%s: %s", payload.sport_key, exc.detail)
        raise HTTPException(
            status_code=502,
            detail=f"Player props API error for sport {payload.sport_key}: {exc.detail}",
        )

    _validate_data_source(events, allow_dummy=use_dummy_data)

    events = _filter_upcoming_events_only(events)
    all_markets, _ = collect_available_player_prop_markets(
        events, payload.target_book, payload.compare_book
    )

    available = sorted(all_markets) if all_markets else discovery_markets

    return PlayerPropMarketsResponse(
        sport_key=payload.sport_key, available_markets=available
    )


@app.post("/api/player-props", response_model=PlayerPropsResponse)
def get_player_props(payload: PlayerPropsRequest) -> PlayerPropsResponse:
    """
    Get player prop value plays for a specific sport and market.
    Events can be narrowed by team but are not filtered by player name.
    """
    target_book = payload.target_book
    compare_book = payload.compare_book
    requested_markets = payload.resolve_markets()

    logger.info(
        "Player props request received: sport=%s markets=%s target=%s compare=%s team=%s event_id=%s use_dummy=%s",
        payload.sport_key,
        ",".join(requested_markets),
        target_book,
        compare_book,
        payload.team,
        payload.event_id,
        payload.use_dummy_data,
    )

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)
    credit_tracker = (
        ApiCreditTracker() if TRACE_LOGGING_ENABLED and not use_dummy_data else None
    )

    # Validate sport key against local schema
    schema = _load_sports_schema()
    available_keys = {item.get('key') for item in schema if isinstance(item, dict) and item.get('key')}
    if payload.sport_key not in available_keys:
        raise HTTPException(status_code=400, detail=f"Unknown sport key: {payload.sport_key}. See /api/sports for available keys.")

    ensure_player_props_supported(payload.sport_key)

    if payload.player_name:
        logger.info(
            "Player filter provided (%s) but ignored; player props now search all players",
            payload.player_name,
        )

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    api_key = _resolve_api_key(use_dummy_data)

    bookmaker_keys = [target_book, compare_book]
    regions = odds_repository.compute_regions(bookmaker_keys)

    logger.info(
        "Computed regions for player props: regions=%s bookmaker_keys=%s",
        regions,
        bookmaker_keys,
    )

    market_param = ",".join(requested_markets)
    discovery_markets = payload.PLAYER_PROP_MARKETS_BY_SPORT.get(
        payload.sport_key, payload.ALL_PLAYER_PROP_MARKETS
    )
    discovery_market_param = ",".join(discovery_markets)

    logger.info(
        "Fetching player props data: sport=%s markets=%s regions=%s dummy=%s",
        payload.sport_key,
        discovery_market_param,
        regions,
        use_dummy_data,
    )
    try:
        events = odds_repository.get_odds_events(
            api_key=api_key,
            sport_key=payload.sport_key,
            markets=discovery_markets,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=use_dummy_data,
            team=payload.team,
            player_name=payload.player_name,
            event_id=payload.event_id,
            credit_tracker=credit_tracker,
            force_player_props=True,
        )
    except HTTPException as exc:
        logger.error("Player props fetch failed for sport=%s: %s", payload.sport_key, exc.detail)
        raise HTTPException(
            status_code=502,
            detail=f"Player props API error for sport {payload.sport_key}: {exc.detail}",
        )

    _validate_data_source(events, allow_dummy=use_dummy_data)

    # Filter by team if specified
    if payload.team and not payload.event_id:
        before_team_filter = len(events)
        team_lower = payload.team.lower()

        def _matches_team(event_team: str) -> bool:
            name = event_team.lower()
            return team_lower in name or name in team_lower

        events = [
            e
            for e in events
            if _matches_team(e.get("home_team", ""))
            or _matches_team(e.get("away_team", ""))
        ]
        logger.info(
            "Filtered player props events by team '%s': %d -> %d",
            payload.team,
            before_team_filter,
            len(events),
        )

    if payload.event_id:
        before_event_filter = len(events)
        events = [e for e in events if e.get("id") == payload.event_id]
        logger.info(
            "Filtered player props events by id '%s': %d -> %d",
            payload.event_id,
            before_event_filter,
            len(events),
        )

    last_update = _extract_latest_update_timestamp(events)

    logger.info("Collected %d player props events before pricing", len(events))

    all_markets_seen, comparable_markets = collect_available_player_prop_markets(
        events, target_book, compare_book
    )

    warnings: List[str] = []

    if payload.sport_key in ("basketball_nba", "americanfootball_nfl"):
        available_markets_message = (
            "Available player prop markets for %s: %s"
            % (
                payload.sport_key,
                ", ".join(sorted(all_markets_seen))
                if all_markets_seen
                else "(none)",
            )
        )
        logger.info(available_markets_message)
        if not all_markets_seen:
            warnings.append(available_markets_message)

    markets_with_prices_message = (
        "Markets with prices from both %s and %s: %s"
        % (
            target_book,
            compare_book,
            ", ".join(sorted(comparable_markets))
            if comparable_markets
            else "(none)",
        )
    )

    logger.info(markets_with_prices_message)
    if not comparable_markets:
        warnings.append(markets_with_prices_message)

    markets_to_process = [m for m in requested_markets if m in comparable_markets]
    if not markets_to_process:
        markets_to_process = [m for m in requested_markets if m in all_markets_seen]
    if not markets_to_process:
        markets_to_process = requested_markets

    if not events:
        detail_parts = [
            f"sport={payload.sport_key}",
            f"markets={market_param}",
        ]
        if payload.team:
            detail_parts.append(f"team={payload.team}")
        if payload.event_id:
            detail_parts.append(f"event_id={payload.event_id}")

        message = "No player props lines found for " + ", ".join(detail_parts)
        logger.warning(message)
        raise HTTPException(status_code=404, detail=message)

    all_filtered: List[ValuePlayOutcome] = []
    now_utc = datetime.now(timezone.utc)

    for market_key in markets_to_process:
        raw_plays = collect_value_plays(events, market_key, target_book, compare_book)

        logger.info(
            "Computed %d raw player props plays for market=%s",
            len(raw_plays),
            market_key,
        )

        for p in raw_plays:
            if not p.start_time:
                continue
            try:
                dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt <= now_utc:
                continue

            if p.start_time:
                p.start_time = format_start_time_est(p.start_time)
            if not p.market:
                p.market = market_key
            all_filtered.append(p)

    # Sort by hedge opportunity (arb margin) then EV
    def ev_sort_key(play: ValuePlayOutcome) -> float:
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(all_filtered, key=ev_sort_key, reverse=True)

    logger.info(
        "Returning %d player props plays after filtering and sorting",
        len(top_plays),
    )

    if credit_tracker:
        logger.info(
            "SpotOddsAPI credits used for /api/player-props: %d (sport=%s markets=%s)",
            credit_tracker.total_credits_used,
            payload.sport_key,
            market_param,
        )

    return PlayerPropsResponse(
        target_book=target_book,
        compare_book=compare_book,
        markets=markets_to_process,
        plays=top_plays,
        warnings=warnings,
        last_update=last_update,
    )


@app.post("/api/player-props/arbitrage-all", response_model=PlayerPropArbitrageResponse)
def get_all_sport_player_prop_arbitrage(
    payload: PlayerPropArbitrageRequest,
) -> PlayerPropArbitrageResponse:
    """Scan all supported player-prop sports for arbitrage vs the comparison book."""

    compare_book = payload.compare_book
    target_books = [book for book in (payload.target_books or ["draftkings", "fanduel", "fliff"]) if book]
    if not target_books:
        raise HTTPException(status_code=400, detail="At least one target book is required.")

    sport_keys = payload.sport_keys or list(PlayerPropsRequest.PLAYER_PROP_MARKETS_BY_SPORT.keys())
    if not sport_keys:
        raise HTTPException(status_code=400, detail="No sports provided for player prop arbitrage search.")

    # Validate sport keys against schema
    schema = _load_sports_schema()
    available_keys = {item.get("key") for item in schema if isinstance(item, dict) and item.get("key")}
    for key in sport_keys:
        if key not in available_keys:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown sport key: {key}. See /api/sports for available keys.",
            )

    use_dummy_data = _require_dummy_data_allowed(payload.use_dummy_data)
    credit_tracker = (
        ApiCreditTracker() if TRACE_LOGGING_ENABLED and not use_dummy_data else None
    )

    api_key = _resolve_api_key(use_dummy_data)

    bookmaker_keys = sorted(set(target_books + [compare_book]))

    warnings: List[str] = []
    all_plays: List[PlayerPropArbOutcome] = []

    def _filter_and_format_player_prop_plays(
        raw_plays: List[ValuePlayOutcome], market_key: str
    ) -> List[ValuePlayOutcome]:
        now_utc = datetime.now(timezone.utc)
        filtered: List[ValuePlayOutcome] = []

        for play in raw_plays:
            if not play.start_time:
                continue

            try:
                dt = datetime.fromisoformat(play.start_time.replace("Z", "+00:00"))
            except Exception:
                continue

            if dt <= now_utc:
                continue

            if play.start_time:
                play.start_time = format_start_time_est(play.start_time)
            if not play.market:
                play.market = market_key
            filtered.append(play)

        return filtered

    for sport_key in sport_keys:
        discovery_markets = PlayerPropsRequest.PLAYER_PROP_MARKETS_BY_SPORT.get(
            sport_key, PlayerPropsRequest.ALL_PLAYER_PROP_MARKETS
        )

        try:
            events = odds_repository.get_odds_events(
                api_key=api_key,
                sport_key=sport_key,
                markets=discovery_markets,
                bookmaker_keys=bookmaker_keys,
                use_dummy_data=use_dummy_data,
                credit_tracker=credit_tracker,
                force_player_props=True,
            )
        except HTTPException as exc:
            warnings.append(f"Player props API error for {sport_key}: {exc.detail}")
            continue

        _validate_data_source(events, allow_dummy=use_dummy_data)
        events = _filter_upcoming_events_only(events)

        if not events:
            warnings.append(f"No upcoming player props found for {sport_key}.")
            continue

        for target_book in target_books:
            if target_book == compare_book:
                continue

            all_markets_seen, comparable_markets = collect_available_player_prop_markets(
                events, target_book, compare_book
            )

            markets_to_process = [m for m in discovery_markets if m in comparable_markets]
            if not markets_to_process:
                markets_to_process = [m for m in discovery_markets if m in all_markets_seen]
            if not markets_to_process:
                warnings.append(
                    f"No overlapping player prop markets for {sport_key} between {target_book} and {compare_book}."
                )
                continue

            for market_key in markets_to_process:
                raw_plays = collect_value_plays(events, market_key, target_book, compare_book)
                filtered = _filter_and_format_player_prop_plays(raw_plays, market_key)

                for play in filtered:
                    if play.arb_margin_percent is None:
                        continue

                    all_plays.append(
                        PlayerPropArbOutcome(
                            **play.dict(),
                            sport_key=sport_key,
                            target_book=target_book,
                        )
                    )

    def _arb_sort_key(play: PlayerPropArbOutcome) -> float:
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        return -1_000_000.0 + play.ev_percent

    all_plays = sorted(all_plays, key=_arb_sort_key, reverse=True)

    max_results = payload.max_results or 100
    if max_results > 0:
        all_plays = all_plays[:max_results]

    if credit_tracker:
        logger.info(
            "SpotOddsAPI credits used for /api/player-props/arbitrage-all: %d (sports=%s targets=%s compare=%s)",
            credit_tracker.total_credits_used,
            ",".join(sport_keys),
            ",".join(target_books),
            compare_book,
        )

    return PlayerPropArbitrageResponse(
        compare_book=compare_book,
        target_books=target_books,
        plays=all_plays,
        used_dummy_data=use_dummy_data,
        warnings=warnings,
    )


@app.get("/api/check-active-odds")
def check_active_odds(sport: str, bookmaker: str):
    """
    Check if there are active odds available for a given sport and bookmaker.
    Returns True if there are upcoming events with odds from the bookmaker.
    """
    try:
        api_key = _resolve_api_key(False)
    except HTTPException:
        return {"has_active_odds": False}

    bookmaker_keys = [bookmaker]

    try:
        events = odds_repository.get_odds_events(
            api_key=api_key,
            sport_key=sport,
            markets="h2h",
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=False,
        )
        
        # Check if there are any events with odds from this bookmaker
        now_utc = datetime.now(timezone.utc)
        has_active = False
        
        for event in events:
            # Check if event has this bookmaker
            for bookmaker_data in event.get("bookmakers", []):
                if bookmaker_data.get("key", "").lower() == bookmaker.lower():
                    # Check if event is in the future
                    start_time = event.get("commence_time")
                    if start_time:
                        try:
                            event_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                            if event_dt > now_utc:
                                has_active = True
                                break
                        except Exception:
                            pass
                if has_active:
                    break
            if has_active:
                break
        
        return {"has_active_odds": has_active}
    except Exception as e:
        # On error, return False
        print(f"Error checking active odds for {sport}/{bookmaker}: {e}")
        return {"has_active_odds": False}


@app.get("/api/credits")
def get_api_credits():
    """
    Get API subscription usage credits.
    Returns usage information from API response headers.
    """
    api_credits = None
    
    # Get API credits from a lightweight API call
    try:
        api_key = get_api_key()
        # Make a minimal API call to get usage headers
        # Using sports endpoint as it's lightweight
        url = f"{BASE_URL}/sports"
        params = {"apiKey": api_key}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            used = response.headers.get("x-requests-used")
            remaining = response.headers.get("x-requests-remaining")

            if used is not None and remaining is not None:
                try:
                    used_int = int(used)
                    remaining_int = int(remaining)
                    total_from_headers = used_int + remaining_int
                    total = max(total_from_headers, API_REQUEST_LIMIT)
                    remaining_calculated = max(remaining_int, total - used_int)
                    api_credits = {
                        "used": used_int,
                        "remaining": remaining_calculated,
                        "total": total,
                        "display": f"{used_int}/{total}"
                    }
                except (ValueError, TypeError):
                    pass
    except Exception as e:
        # If API key is not available or call fails, return None
        print(f"Error fetching API credits: {e}")
    
    return {
        "api_credits": api_credits
    }


class SMSAlertRequest(BaseModel):
    phone: str
    message: str


class LineTrackerRequest(BaseModel):
    """
    Request body for /api/line-tracker:
      - sport_key: e.g. "americanfootball_nfl"
      - home_query / away_query: substrings to match teams (case-insensitive)
      - bookmaker_keys: list of books to include
      - track_ml / track_spreads / track_totals: which markets to include
    """
    sport_key: str
    home_query: str
    away_query: str
    bookmaker_keys: List[str]
    track_ml: bool = True
    track_spreads: bool = False
    track_totals: bool = False


class LineTrackerEvent(BaseModel):
    event_id: str
    home_team: str
    away_team: str
    start_time: Optional[str]
    lines: Dict[str, Dict[str, Any]]


class LineTrackerSnapshot(BaseModel):
    timestamp: str
    sport_key: str
    regions: str
    markets: List[str]
    bookmaker_keys: List[str]
    events: List[LineTrackerEvent]


def _ensure_logs_dir() -> str:
    """Return path to logs directory, creating it if needed."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _log_line_tracker_snapshot(record: Dict[str, Any]) -> None:
    """
    Append one line-movement snapshot to logs/line_movement_tracker.jsonl.
    Failures here should never break the main request flow.
    """
    try:
        logs_dir = _ensure_logs_dir()
        log_path = os.path.join(logs_dir, "line_movement_tracker.jsonl")
        record.setdefault("log_type", "line_movement_tracker")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record))
            f.write("\n")
    except Exception:
        # Silent failure – logging should not impact live behavior.
        pass


def _matches_team_query(query: str, team_name: Optional[str]) -> bool:
    """Case-insensitive substring match helper for team selection."""
    if not query or not team_name:
        return False
    return query.lower() in team_name.lower()


def _extract_line_tracker_markets(
    event: Dict[str, Any],
    bookmaker_keys: List[str],
    track_ml: bool,
    track_spreads: bool,
    track_totals: bool,
) -> Dict[str, Dict[str, Any]]:
    """
    Extract ML, spread, and total info for an event for each requested bookmaker.
    Returns a dict keyed by bookmaker with nested market data.
    """
    home = event.get("home_team")
    away = event.get("away_team")

    per_book: Dict[str, Dict[str, Any]] = {}

    for bookmaker in event.get("bookmakers", []):
        book_key = bookmaker.get("key")
        if book_key not in bookmaker_keys:
            continue

        book_entry: Dict[str, Any] = {}

        # Moneyline (h2h)
        if track_ml:
            h2h_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "h2h"),
                None,
            )
            if h2h_market:
                home_price = None
                away_price = None
                for outcome in h2h_market.get("outcomes", []):
                    name = outcome.get("name")
                    price = sanitize_american_price(outcome.get("price"))
                    if name == home:
                        home_price = price
                    elif name == away:
                        away_price = price
                book_entry["moneyline"] = {
                    "home_price": home_price,
                    "away_price": away_price,
                }

        # Spreads
        if track_spreads:
            spread_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "spreads"),
                None,
            )
            if spread_market:
                home_point = None
                home_price = None
                away_point = None
                away_price = None
                for outcome in spread_market.get("outcomes", []):
                    name = outcome.get("name")
                    price = sanitize_american_price(outcome.get("price"))
                    if name == home:
                        home_point = outcome.get("point")
                        home_price = price
                    elif name == away:
                        away_point = outcome.get("point")
                        away_price = price
                book_entry["spread"] = {
                    "home_point": home_point,
                    "home_price": home_price,
                    "away_point": away_point,
                    "away_price": away_price,
                }

        # Totals
        if track_totals:
            totals_market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == "totals"),
                None,
            )
            if totals_market:
                total_point = None
                over_price = None
                under_price = None
                for outcome in totals_market.get("outcomes", []):
                    name = outcome.get("name", "")
                    price = sanitize_american_price(outcome.get("price"))
                    point = outcome.get("point")
                    if "over" in name.lower():
                        total_point = point
                        over_price = price
                    elif "under" in name.lower():
                        total_point = point
                        under_price = price
                book_entry["total"] = {
                    "point": total_point,
                    "over_price": over_price,
                    "under_price": under_price,
                }

        if book_entry:
            per_book[book_key] = book_entry

    return per_book


@app.post("/api/send-sms")
def send_sms_alert(payload: SMSAlertRequest):
    """
    Send SMS alert via Textbelt API.
    
    Parameters:
    - phone: Phone number in format like "5551234567" or "+15551234567"
    - message: Message text to send
    """
    textbelt_key = get_textbelt_api_key()
    if not textbelt_key:
        raise HTTPException(
            status_code=400,
            detail="Textbelt API key not configured. Set TEXTBELT_API_KEY environment variable.",
        )
    
    # Clean phone number (remove any non-digit characters except +)
    phone = payload.phone.strip()
    # Remove + if present, Textbelt expects just digits
    if phone.startswith("+"):
        phone = phone[1:]
    # Remove any remaining non-digit characters
    phone = "".join(filter(str.isdigit, phone))
    
    if not phone or len(phone) < 10:
        raise HTTPException(
            status_code=400,
            detail="Invalid phone number format. Please provide a valid phone number.",
        )
    
    # Textbelt API endpoint
    url = "https://textbelt.com/text"
    
    # Prepare request data
    data = {
        "phone": phone,
        "message": payload.message,
        "key": textbelt_key
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        if result.get("success"):
            return {
                "success": True,
                "message": "SMS sent successfully",
                "quotaRemaining": result.get("quotaRemaining")
            }
        else:
            error_msg = result.get("error", "Unknown error")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to send SMS: {error_msg}"
            )
    except requests.exceptions.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with Textbelt API: {str(e)}"
        )


@app.post("/api/line-tracker", response_model=LineTrackerSnapshot)
def get_line_tracker_snapshot(payload: LineTrackerRequest) -> LineTrackerSnapshot:
    """
    Return a one-shot snapshot of lines (ML/spread/total) for a specific game,
    and log it to logs/line_movement_tracker.jsonl.

    The frontend is responsible for polling this endpoint (e.g. every minute)
    to visualize line movement over time.
    """
    try:
        api_key = _resolve_api_key(False)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    if not payload.bookmaker_keys:
        raise HTTPException(status_code=400, detail="No bookmakers specified")

    regions = odds_repository.compute_regions(payload.bookmaker_keys)

    markets_to_request: List[str] = []
    if payload.track_ml:
        markets_to_request.append("h2h")
    if payload.track_spreads:
        markets_to_request.append("spreads")
    if payload.track_totals:
        markets_to_request.append("totals")
    if not markets_to_request:
        raise HTTPException(status_code=400, detail="At least one market must be selected")

    markets_param = ",".join(markets_to_request)

    try:
        events = odds_repository.get_odds_events(
            api_key=api_key,
            sport_key=payload.sport_key,
            markets=markets_param,
            bookmaker_keys=payload.bookmaker_keys,
            use_dummy_data=False,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error fetching odds: {e}")

    snapshot_events: List[LineTrackerEvent] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        raw_start_time = event.get("commence_time")
        formatted_start_time: Optional[str] = None
        if raw_start_time:
            try:
                formatted_start_time = format_start_time_est(raw_start_time)
            except Exception:
                # If formatting fails, fall back to raw value
                formatted_start_time = raw_start_time

        # Match either (home_query -> home, away_query -> away) OR swapped,
        # so the user doesn't have to know which team is home.
        direct_match = (
            _matches_team_query(payload.home_query, home)
            and _matches_team_query(payload.away_query, away)
        )
        swapped_match = (
            _matches_team_query(payload.home_query, away)
            and _matches_team_query(payload.away_query, home)
        )
        if not (direct_match or swapped_match):
            continue

        lines = _extract_line_tracker_markets(
            event=event,
            bookmaker_keys=payload.bookmaker_keys,
            track_ml=payload.track_ml,
            track_spreads=payload.track_spreads,
            track_totals=payload.track_totals,
        )
        if not lines:
            continue

        snapshot_events.append(
            LineTrackerEvent(
                event_id=event.get("id", ""),
                home_team=home or "",
                away_team=away or "",
                start_time=formatted_start_time,
                lines=lines,
            )
        )

    now_utc = datetime.utcnow().isoformat() + "Z"
    snapshot_dict: Dict[str, Any] = {
        "timestamp": now_utc,
        "sport_key": payload.sport_key,
        "regions": regions,
        "markets": markets_to_request,
        "bookmaker_keys": payload.bookmaker_keys,
        "events": [e.dict() for e in snapshot_events],
    }

    # Persist snapshot to logs for later analysis.
    _log_line_tracker_snapshot(snapshot_dict)

    # Return structured response to the frontend.
    return LineTrackerSnapshot(**snapshot_dict)


@app.get("/api/test-arbitrage-alert")
def get_test_arbitrage_alert():
    """
    Returns a mock arbitrage opportunity for testing the watcher text feature.
    This creates a fake play with positive arbitrage margin to test SMS alerts.
    """
    # Create a mock arbitrage opportunity
    now_utc = datetime.now(timezone.utc)
    future_time = (now_utc + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    formatted_time = format_start_time_est(future_time)
    
    # Create a test play with positive arbitrage margin (e.g., 2.5%)
    test_play = BestValuePlayOutcome(
        sport_key="basketball_nba",
        market="h2h",
        event_id="test_arbitrage_001",
        matchup="Lakers @ Warriors",
        start_time=formatted_time,
        outcome_name="Lakers",
        point=None,
        novig_price=-110,  # Novig odds for Lakers
        novig_reverse_name="Warriors",
        novig_reverse_price=105,  # Novig odds for opposite side (Warriors)
        book_price=-105,  # Better odds at target book (DraftKings)
        ev_percent=2.5,  # Positive EV
        hedge_ev_percent=1.8,
        is_arbitrage=True,
        arb_margin_percent=2.5,  # Positive arbitrage margin
    )
    
    return BestValuePlaysResponse(
        target_book="draftkings",
        compare_book="novig",
        plays=[test_play],
    )


# Redirect root to the main page
@app.get("/")
async def root():
    return RedirectResponse(url="/BensSportsBookApp.html")


@app.get("/ArbritrageBetFinder.html")
async def legacy_arbitrage_page():
    """Redirect legacy URL with misspelling to the corrected filename."""
    return RedirectResponse(url="/BensSportsBookApp.html", status_code=301)


# Static frontend (BensSportsBookApp.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Odds Price Alert FastAPI server")
    parser.add_argument("-DummyData", "--dummy-data", action="store_true", help="Serve mock data instead of real API calls")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")

    args = parser.parse_args()

    uvicorn.run("main:app", host=args.host, port=args.port, reload=args.reload)
