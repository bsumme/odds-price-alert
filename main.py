import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import shared utilities
from services.odds_api import get_api_key, fetch_odds, BASE_URL
from services.odds_utils import (
    american_to_decimal,
    estimate_ev_percent,
    points_match,
    apply_vig_adjustment,
    MAX_VALID_AMERICAN_ODDS,
)
from utils.regions import compute_regions_for_books
from utils.formatting import pretty_book_label, format_start_time_est

# -------------------------------------------------------------------
# Pydantic Models
# -------------------------------------------------------------------


class PriceOut(BaseModel):
    bookmaker_key: str
    bookmaker_name: str
    price: Optional[int]  # the best price for that side, if available


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
    novig_price: int
    novig_reverse_name: Optional[str]
    novig_reverse_price: Optional[int]
    book_price: int
    ev_percent: float        # estimated edge in percent (vs Novig same side)
    hedge_ev_percent: Optional[float] = None  # legacy: edge vs Novig opposite side (not used for sort)
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


class PlayerPropsRequest(BaseModel):
    """
    Request body for /api/player-props:
      - sport_key: e.g. "basketball_nba" or "americanfootball_nfl"
      - team: team name to filter by (optional, can be None to search all teams)
      - player_name: player name to filter by (optional, can be None to search all players)
      - market: player prop market like "player_points", "player_assists", "player_rebounds", etc.
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "novig" (the book to compare against)
      - use_dummy_data: if True, use mock data instead of real API calls
    """
    sport_key: str
    team: Optional[str] = None
    player_name: Optional[str] = None
    market: str
    target_book: str
    compare_book: str
    use_dummy_data: bool = False


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
    market: str,
    team: Optional[str],
    player_name: Optional[str],
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Generate dummy player props data for development.
    """
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
    
    player_map = nba_players if sport_key == "basketball_nba" else nfl_players
    
    # Determine which teams and players to use
    if team and team in player_map:
        teams_to_use = [team]
    else:
        teams_to_use = list(player_map.keys())[:3]  # Use first 3 teams
    
    # Market-specific point ranges
    point_ranges = {
        "player_points": (20.5, 35.5) if sport_key == "basketball_nba" else (50.5, 300.5),
        "player_assists": (5.5, 12.5),
        "player_rebounds": (8.5, 15.5),
        "player_reception_yards": (50.5, 120.5),
        "player_passing_yards": (200.5, 350.5),
        "player_rushing_yards": (50.5, 120.5),
        "player_touchdowns": (0.5, 2.5),
    }
    
    default_range = (20.5, 35.5)
    point_range = point_ranges.get(market, default_range)
    
    now = datetime.now(timezone.utc)
    events = []
    for team_name in teams_to_use:
        players = player_map[team_name]
        
        # Filter by player_name if specified
        if player_name:
            players = [p for p in players if player_name.lower() in p.lower()]
            if not players:
                continue
        
        # Generate event for each player (up to 2 players per team)
        for player in players[:2]:
            hours_ahead = random.randint(24, 168)
            commence_time = (now + timedelta(hours=hours_ahead)).isoformat().replace("+00:00", "Z")
            event_id = f"dummy_{sport_key}_{team_name}_{player}_{int(now.timestamp())}"
            
            # Generate point line
            point = round(random.uniform(point_range[0], point_range[1]) * 2) / 2  # Round to 0.5
            
            # Generate opponent team (simplified)
            opponent = random.choice([t for t in player_map.keys() if t != team_name])
            home_team = random.choice([team_name, opponent])
            away_team = opponent if home_team == team_name else team_name
            
            bookmakers = []
            
            # Generate Novig odds first (best)
            for book_key in bookmaker_keys:
                if book_key.lower() == "novig":
                    over_odds = -105
                    under_odds = -105
                    bookmakers.append({
                        "key": book_key,
                        "title": book_key.title(),
                        "markets": [{
                            "key": market,
                            "outcomes": [
                                {"name": "Over", "description": player, "price": over_odds, "point": point},
                                {"name": "Under", "description": player, "price": under_odds, "point": point},
                            ]
                        }]
                    })
                    break
            
            # Generate other books' odds (worse)
            for book_key in bookmaker_keys:
                if book_key.lower() == "novig":
                    continue
                
                over_odds = random.choice([-110, -115])
                under_odds = random.choice([-110, -115])
                
                bookmakers.append({
                    "key": book_key,
                    "title": book_key.title(),
                    "markets": [{
                        "key": market,
                        "outcomes": [
                            {"name": "Over", "description": player, "price": over_odds, "point": point},
                            {"name": "Under", "description": player, "price": under_odds, "point": point},
                        ]
                    }]
                })
            
            events.append({
                "id": event_id,
                "sport_key": sport_key,
                "home_team": home_team,
                "away_team": away_team,
                "commence_time": commence_time,
                "bookmakers": bookmakers,
            })
    
    return events


def fetch_odds_with_dummy(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
) -> List[Dict[str, Any]]:
    """
    Wrapper around fetch_odds that handles dummy data generation.
    """
    if use_dummy_data:
        return generate_dummy_odds_data(sport_key, markets, bookmaker_keys)
    return fetch_odds(api_key, sport_key, regions, markets, bookmaker_keys, use_dummy_data=False)


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

        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            if key == compare_book:
                compare_market = market
            elif key == target_book:
                book_market = market

        if not compare_market or not book_market:
            continue

        # Allow 0.5-point flex for spreads, totals, and player props (Odds API sometimes
        # differs by 0.5 between books).
        is_player_prop = market_key.startswith("player_")
        allow_half_point_flex = market_key in ("totals", "spreads") or is_player_prop

        compare_outcomes: List[Dict[str, Any]] = []
        for o in compare_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            description = o.get("description", None)  # For player props, this is the player name
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                # Skip absurd values like -100000
                continue
            compare_outcomes.append(
                {"name": name, "price": price, "point": point, "description": description}
            )

        if not compare_outcomes:
            continue

        for o in book_market.get("outcomes", []):
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)
            description = o.get("description", None)  # For player props, this is the player name
            if name is None or price is None:
                continue
            if abs(price) >= MAX_VALID_AMERICAN_ODDS:
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
            else:
                # Apply vig adjustment to target book odds (makes them less favorable)
                adjusted_price = apply_vig_adjustment(price, target_book)

            # For player props, match by name, description (player), and point
            matching_compare = None
            if is_player_prop and description:
                # Find matching outcome with same name, description, and point
                for comp_outcome in compare_outcomes:
                    comp_name = comp_outcome.get("name")
                    comp_desc = comp_outcome.get("description")
                    comp_point = comp_outcome.get("point", None)
                    if (comp_name == name and 
                        comp_desc and description and 
                        comp_desc.lower() == description.lower() and
                        points_match(point, comp_point, allow_half_point_flex)):
                        matching_compare = comp_outcome
                        break
            else:
                matching_compare = find_best_comparison_outcome(
                    outcomes=compare_outcomes,
                    name=name,
                    point=point,
                    allow_half_point_flex=allow_half_point_flex,
                )
            if matching_compare is None:
                continue

            compare_price = matching_compare["price"]
            ev_pct = estimate_ev_percent(book_odds=adjusted_price, sharp_odds=compare_price)

            # Find the *other* comparison book side (hedge side) with matching/close point
            other_compare = None
            if is_player_prop and description:
                # For player props, find opposite side (Over -> Under or vice versa) with same player and point
                opposite_name = "Under" if name == "Over" else "Over"
                for comp_outcome in compare_outcomes:
                    comp_name = comp_outcome.get("name")
                    comp_desc = comp_outcome.get("description")
                    comp_point = comp_outcome.get("point", None)
                    if (comp_name == opposite_name and 
                        comp_desc and description and 
                        comp_desc.lower() == description.lower() and
                        points_match(point, comp_point, allow_half_point_flex)):
                        other_compare = comp_outcome
                        break
            else:
                other_compare = find_best_comparison_outcome(
                    outcomes=compare_outcomes,
                    name=name,
                    point=point,
                    allow_half_point_flex=allow_half_point_flex,
                    opposite=True,
                )

            novig_reverse_name: Optional[str] = None
            novig_reverse_price: Optional[int] = None
            hedge_ev_percent: Optional[float] = None
            is_arb = False
            arb_margin_percent: Optional[float] = None

            if other_compare is not None:
                novig_reverse_name = other_compare.get("name")
                novig_reverse_price = other_compare.get("price")
                hedge_ev_percent = estimate_ev_percent(
                    book_odds=adjusted_price, sharp_odds=novig_reverse_price
                )

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
                if arb_margin_percent > 0:
                    is_arb = True


            # For player props, include player name in outcome_name
            outcome_display_name = name
            if is_player_prop and description:
                outcome_display_name = f"{description} {name}"
            # For totals, include the point value in outcome_name (e.g., "Over 225.5")
            elif market_key == "totals" and point is not None:
                outcome_display_name = f"{name} {point}"
            
            reverse_display_name = novig_reverse_name
            if is_player_prop and other_compare and other_compare.get("description"):
                reverse_desc = other_compare.get("description")
                reverse_display_name = f"{reverse_desc} {novig_reverse_name}" if novig_reverse_name else None
            # For totals, include the point value in reverse outcome_name
            elif market_key == "totals" and novig_reverse_name and point is not None:
                reverse_display_name = f"{novig_reverse_name} {point}"

            plays.append(
                ValuePlayOutcome(
                    event_id=event_id,
                    matchup=matchup,
                    start_time=start_time,
                    outcome_name=outcome_display_name,
                    point=point,
                    novig_price=compare_price,
                    novig_reverse_name=reverse_display_name,
                    novig_reverse_price=novig_reverse_price,
                    book_price=adjusted_price,  # Use adjusted price with vig
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


@app.post("/api/odds", response_model=OddsResponse)
def get_odds(payload: OddsRequest) -> OddsResponse:
    """
    Odds endpoint used by the watcher UI: returns current prices and best line
    for specific teams/bets the user is tracking.
    """
    if not payload.bets:
        raise HTTPException(status_code=400, detail="No bets provided")

    api_key = ""
    if not payload.use_dummy_data:
        try:
            api_key = get_api_key()
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    all_book_keys: Set[str] = set()
    for bet in payload.bets:
        all_book_keys.update(bet.bookmaker_keys)

    if not all_book_keys:
        raise HTTPException(status_code=400, detail="No bookmakers specified")

    regions = compute_regions_for_books(list(all_book_keys))

    all_bets_results: List[SingleBetOdds] = []

    by_sport: Dict[str, List[BetRequest]] = {}
    for bet in payload.bets:
        by_sport.setdefault(bet.sport_key, []).append(bet)

    for sport_key, bets_for_sport in by_sport.items():
        markets = sorted({b.market for b in bets_for_sport})
        bookmaker_keys = sorted({bk for b in bets_for_sport for bk in b.bookmaker_keys})

        events = fetch_odds_with_dummy(
            api_key=api_key,
            sport_key=sport_key,
            regions=regions,
            markets=",".join(markets),
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=payload.use_dummy_data,
        )

        for bet in bets_for_sport:
            prices_per_book: List[PriceOut] = []

            for book_key in bet.bookmaker_keys:
                price_for_team: Optional[int] = None

                for event in events:
                    home = event.get("home_team")
                    away = event.get("away_team")

                    if bet.team not in (home, away):
                        continue

                    book_market = None
                    for bookmaker in event.get("bookmakers", []):
                        if bookmaker.get("key") != book_key:
                            continue
                        book_market = next(
                            (m for m in bookmaker.get("markets", []) if m.get("key") == bet.market),
                            None,
                        )
                        if book_market:
                            break
                    if not book_market:
                        continue

                    for outcome in book_market.get("outcomes", []):
                        name = outcome.get("name")
                        price = outcome.get("price")
                        point = outcome.get("point", None)

                        if name != bet.team:
                            continue

                        if bet.point is not None:
                            if point is None:
                                continue
                            if abs(point - bet.point) > 1e-6:
                                continue

                        if price is None:
                            continue
                        if abs(price) >= MAX_VALID_AMERICAN_ODDS:
                            continue

                        price_for_team = price
                        break

                    if price_for_team is not None:
                        break

                prices_per_book.append(
                    PriceOut(
                        bookmaker_key=book_key,
                        bookmaker_name=pretty_book_label(book_key),
                        price=price_for_team,
                    )
                )

            valid_prices = [
                (bk, p)
                for bk, p in [(po.bookmaker_key, po.price) for po in prices_per_book]
                if p is not None
            ]
            best_price_for_team: Optional[int] = None
            best_book: Optional[str] = None
            if valid_prices:
                best_book, best_price_for_team = max(valid_prices, key=lambda x: american_to_decimal(x[1]))

            for po in prices_per_book:
                if po.price is None and po.bookmaker_key == best_book:
                    po.price = best_price_for_team

            all_bets_results.append(
                SingleBetOdds(
                    sport_key=sport_key,
                    market=bet.market,
                    team=bet.team,
                    point=bet.point,
                    prices=prices_per_book,
                )
            )

    return OddsResponse(bets=all_bets_results)


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
    market_key = payload.market

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    api_key = ""
    if not payload.use_dummy_data:
        try:
            api_key = get_api_key()
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, compare_book]
    regions = compute_regions_for_books(bookmaker_keys)

    events = fetch_odds_with_dummy(
        api_key=api_key,
        sport_key=payload.sport_key,
        regions=regions,
        markets=market_key,
        bookmaker_keys=bookmaker_keys,
        use_dummy_data=payload.use_dummy_data,
    )

    raw_plays = collect_value_plays(events, market_key, target_book, compare_book)

    # Filter out live events and games that have already started
    now_utc = datetime.now(timezone.utc)
    filtered_plays: List[ValuePlayOutcome] = []
    for p in raw_plays:
        if not p.start_time:
            # If no start time, exclude it to be safe
            continue
        try:
            dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
            # Only include games that haven't started yet (start_time is in the future)
            if dt > now_utc:
                filtered_plays.append(p)
        except Exception:
            # If we can't parse the time, exclude it to be safe
            continue

    # Convert start_time into an easy-to-read EST string for display
    for p in filtered_plays:
        if p.start_time:
            p.start_time = format_start_time_est(p.start_time)

    # Sort primarily by hedge opportunity (arb_margin_percent) descending.
    # Plays with no comparison book opposite side get pushed to the bottom.
    def hedge_sort_key(play: ValuePlayOutcome) -> float:
        """
        Sort plays by hedge margin first. Plays without an opposite comparison book side
        get a large negative default so they appear at the bottom.
        """
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        # No opposite side: effectively no hedge opportunity.
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(filtered_plays, key=hedge_sort_key, reverse=True)


    # Respect max_results if provided
    max_results = getattr(payload, "max_results", None)
    if max_results is not None and max_results > 0:
        top_plays = top_plays[:max_results]

    return ValuePlaysResponse(
        target_book=target_book,
        compare_book=compare_book,
        market=market_key,
        plays=top_plays,
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

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, compare_book]
    regions = compute_regions_for_books(bookmaker_keys)

    all_plays: List[BestValuePlayOutcome] = []

    # Search across all sport/market combinations
    for sport_key in payload.sport_keys:
        for market_key in payload.markets:
            try:
                events = fetch_odds_with_dummy(
                    api_key=api_key,
                    sport_key=sport_key,
                    regions=regions,
                    markets=market_key,
                    bookmaker_keys=bookmaker_keys,
                    use_dummy_data=payload.use_dummy_data,
                )

                raw_plays = collect_value_plays(events, market_key, target_book, compare_book)

                # Filter out live events and games that have already started
                now_utc = datetime.now(timezone.utc)
                filtered_plays: List[ValuePlayOutcome] = []
                for p in raw_plays:
                    if not p.start_time:
                        # If no start time, exclude it to be safe
                        continue
                    try:
                        dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
                        # Only include games that haven't started yet (start_time is in the future)
                        if dt > now_utc:
                            filtered_plays.append(p)
                    except Exception:
                        # If we can't parse the time, exclude it to be safe
                        continue

                # Convert to BestValuePlayOutcome with sport and market info
                for p in filtered_plays:
                    formatted_time = p.start_time
                    if formatted_time:
                        formatted_time = format_start_time_est(formatted_time)

                    all_plays.append(
                        BestValuePlayOutcome(
                            sport_key=sport_key,
                            market=market_key,
                            event_id=p.event_id,
                            matchup=p.matchup,
                            start_time=formatted_time,
                            outcome_name=p.outcome_name,
                            point=p.point,
                            novig_price=p.novig_price,
                            novig_reverse_name=p.novig_reverse_name,
                            novig_reverse_price=p.novig_reverse_price,
                            book_price=p.book_price,
                            ev_percent=p.ev_percent,
                            hedge_ev_percent=p.hedge_ev_percent,
                            is_arbitrage=p.is_arbitrage,
                            arb_margin_percent=p.arb_margin_percent,
                        )
                    )
            except Exception as e:
                # Log error but continue with other sports/markets
                print(f"Error processing {sport_key}/{market_key}: {e}")
                continue

    # Sort by hedge opportunity (arb_margin_percent) descending
    def hedge_sort_key(play: BestValuePlayOutcome) -> float:
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        # No opposite side: effectively no hedge opportunity.
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(all_plays, key=hedge_sort_key, reverse=True)

    # Respect max_results if provided
    max_results = payload.max_results or 50
    if max_results > 0:
        top_plays = top_plays[:max_results]

    return BestValuePlaysResponse(
        target_book=target_book,
        compare_book=compare_book,
        plays=top_plays,
    )


@app.post("/api/player-props", response_model=ValuePlaysResponse)
def get_player_props(payload: PlayerPropsRequest) -> ValuePlaysResponse:
    """
    Get player prop value plays for a specific sport, team, player, and market.
    Filters events to only include those matching the specified team and player.
    """
    target_book = payload.target_book
    compare_book = payload.compare_book
    market_key = payload.market

    if target_book == compare_book:
        raise HTTPException(
            status_code=400,
            detail="Target book and comparison book cannot be the same.",
        )

    api_key = ""
    if not payload.use_dummy_data:
        try:
            api_key = get_api_key()
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

    bookmaker_keys = [target_book, compare_book]
    regions = compute_regions_for_books(bookmaker_keys)

    if payload.use_dummy_data:
        events = generate_dummy_player_props_data(
            sport_key=payload.sport_key,
            market=market_key,
            team=payload.team,
            player_name=payload.player_name,
            bookmaker_keys=bookmaker_keys,
        )
    else:
        # Fetch real odds from API
        events = fetch_odds(
            api_key=api_key,
            sport_key=payload.sport_key,
            regions=regions,
            markets=market_key,
            bookmaker_keys=bookmaker_keys,
            use_dummy_data=False,
        )
        
        # Filter by team if specified
        if payload.team:
            events = [
                e for e in events
                if payload.team in (e.get("home_team", ""), e.get("away_team", ""))
            ]
        
        # Filter by player name if specified
        if payload.player_name:
            filtered_events = []
            for event in events:
                for bookmaker in event.get("bookmakers", []):
                    for market in bookmaker.get("markets", []):
                        if market.get("key") == market_key:
                            for outcome in market.get("outcomes", []):
                                description = outcome.get("description", "")
                                if payload.player_name.lower() in description.lower():
                                    filtered_events.append(event)
                                    break
                            if event in filtered_events:
                                break
                    if event in filtered_events:
                        break
            events = filtered_events

    raw_plays = collect_value_plays(events, market_key, target_book, compare_book)
    
    # Filter by player name in outcomes if specified
    if payload.player_name:
        raw_plays = [
            p for p in raw_plays
            if payload.player_name.lower() in p.outcome_name.lower()
        ]

    # Filter out live events and games that have already started
    now_utc = datetime.now(timezone.utc)
    filtered_plays: List[ValuePlayOutcome] = []
    for p in raw_plays:
        if not p.start_time:
            continue
        try:
            dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
            if dt > now_utc:
                filtered_plays.append(p)
        except Exception:
            continue

    # Convert start_time into an easy-to-read EST string for display
    for p in filtered_plays:
        if p.start_time:
            p.start_time = format_start_time_est(p.start_time)

    # Sort by EV percent descending
    def ev_sort_key(play: ValuePlayOutcome) -> float:
        if play.arb_margin_percent is not None:
            return play.arb_margin_percent
        return -1_000_000.0 + play.ev_percent

    top_plays = sorted(filtered_plays, key=ev_sort_key, reverse=True)

    return ValuePlaysResponse(
        target_book=target_book,
        compare_book=compare_book,
        market=market_key,
        plays=top_plays,
    )


@app.get("/api/check-active-odds")
def check_active_odds(sport: str, bookmaker: str):
    """
    Check if there are active odds available for a given sport and bookmaker.
    Returns True if there are upcoming events with odds from the bookmaker.
    """
    try:
        api_key = get_api_key()
    except RuntimeError:
        # If API key not available, return False
        return {"has_active_odds": False}
    
    # Determine region based on bookmaker
    if bookmaker.lower() == "novig":
        regions = "us_ex"
    elif bookmaker.lower() == "fliff":
        regions = "us2"
    else:
        regions = "us"
    
    try:
        events = fetch_odds(
            api_key=api_key,
            sport_key=sport,
            regions=regions,
            markets="h2h",
            bookmaker_keys=[bookmaker],
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
                    total = used_int + remaining_int
                    api_credits = {
                        "used": used_int,
                        "remaining": remaining_int,
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
                    if name == home:
                        home_price = outcome.get("price")
                    elif name == away:
                        away_price = outcome.get("price")
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
                    if name == home:
                        home_point = outcome.get("point")
                        home_price = outcome.get("price")
                    elif name == away:
                        away_point = outcome.get("point")
                        away_price = outcome.get("price")
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
                    price = outcome.get("price")
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
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not payload.bookmaker_keys:
        raise HTTPException(status_code=400, detail="No bookmakers specified")

    regions = compute_regions_for_books(payload.bookmaker_keys)

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
        events = fetch_odds(
            api_key=api_key,
            sport_key=payload.sport_key,
            regions=regions,
            markets=markets_param,
            bookmaker_keys=payload.bookmaker_keys,
            use_dummy_data=False,
        )
    except requests.HTTPError as http_err:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {http_err.response.status_code}, {http_err.response.text}",
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
    return RedirectResponse(url="/ArbritrageBetFinder.html")

# Static frontend (ArbritrageBetFinder.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
