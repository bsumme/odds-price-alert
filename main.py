import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from zoneinfo import ZoneInfo

BASE_URL = "https://api.the-odds-api.com/v4"

# Treat absurdly large American odds as invalid (e.g. -100000 from Novig)
MAX_VALID_AMERICAN_ODDS = 10000

# -------------------------------------------------------------------
# Shared models and utilities
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
    sgp_suggestion: Optional[Dict[str, Any]] = None  # holds 3-leg SGP suggestion if requested


class ValuePlaysRequest(BaseModel):
    """
    Request body for /api/value-plays:
      - sport_key: e.g. "basketball_nba"
      - target_book: e.g. "draftkings"
      - compare_book: e.g. "fanduel" (the book to compare against)
      - market: "h2h", "spreads", "totals", or "player_points"
      - include_sgp: whether to build a naive 3-leg parlay from the top plays
      - use_dummy_data: if True, use mock data instead of real API calls
    """
    sport_key: str
    target_book: str
    compare_book: str
    market: str
    include_sgp: bool = False
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


BOOK_LABELS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "novig": "Novig",
    "fliff": "Fliff",
    # add more as needed
}


def get_api_key() -> str:
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing THE_ODDS_API_KEY environment variable. "
            "Set it in Windows Environment Variables and restart."
        )
    return api_key


def get_widget_api_key() -> Optional[str]:
    """Get the widget API key from environment variable. Returns None if not set."""
    return os.getenv("THE_ODDS_WIDGET_API_KEY")


def pretty_book_label(book_key: str) -> str:
    return BOOK_LABELS.get(book_key, book_key)


def compute_regions_for_books(bookmaker_keys: List[str]) -> str:
    """
    Decide which regions to request based on which books you're tracking.

    - DraftKings / FanDuel live in "us"
    - Fliff lives in "us2"
    - Novig lives in "us_ex"
    """
    regions: Set[str] = set()
    for bk in bookmaker_keys:
        if bk in ("draftkings", "fanduel"):
            regions.add("us")
        elif bk == "fliff":
            regions.add("us2")
        elif bk == "novig":
            regions.add("us_ex")
        else:
            regions.add("us")

    return ",".join(sorted(regions))


def generate_dummy_odds_data(
    sport_key: str,
    markets: str,
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Generate simple dummy/mock odds data for development.
    Novig always has the best lines (most favorable odds).
    Other books (DK, FD, Fliff) have worse odds, ensuring no positive EV hedges.
    """
    # Sample team names by sport
    team_pairs = {
        "basketball_nba": [
            ("Lakers", "Warriors"),
            ("Celtics", "Heat"),
            ("Nuggets", "Suns"),
            ("Bucks", "76ers"),
            ("Mavericks", "Clippers"),
        ],
        "americanfootball_nfl": [
            ("Chiefs", "Bills"),
            ("49ers", "Cowboys"),
            ("Ravens", "Bengals"),
            ("Dolphins", "Jets"),
            ("Eagles", "Giants"),
        ],
        "basketball_ncaab": [
            ("Duke", "UNC"),
            ("Kentucky", "Kansas"),
            ("UCLA", "Arizona"),
            ("Gonzaga", "Baylor"),
            ("Michigan State", "Indiana"),
        ],
        "americanfootball_ncaaf": [
            ("Alabama", "Georgia"),
            ("Ohio State", "Michigan"),
            ("Clemson", "Florida State"),
            ("Texas", "Oklahoma"),
            ("USC", "Oregon"),
        ],
    }
    
    teams = team_pairs.get(sport_key, [("Team A", "Team B"), ("Team C", "Team D")])
    market_list = markets.split(",") if "," in markets else [markets]
    
    # Generate future start times (next 1-7 days)
    now = datetime.now(timezone.utc)
    events = []
    
    for i, (away, home) in enumerate(teams[:5]):  # Generate 5 events
        # Random future time between 1-7 days from now
        hours_ahead = random.randint(24, 168)
        commence_time = (now + timedelta(hours=hours_ahead)).isoformat().replace("+00:00", "Z")
        
        event_id = f"dummy_{sport_key}_{i}_{int(now.timestamp())}"
        
        # Generate base odds for this event (Novig's "true" odds)
        base_market_odds = {}
        for market_key in market_list:
            if market_key == "h2h":
                # Moneyline: pick realistic odds
                home_base = random.choice([-150, -120, -110, -105, +105, +110, +120, +150])
                away_base = random.choice([-150, -120, -110, -105, +105, +110, +120, +150])
                # Ensure they're somewhat balanced
                if (home_base < -140 and away_base < -140) or (home_base > +140 and away_base > +140):
                    if home_base < -140:
                        away_base = random.choice([+105, +110, +120, +150, +180])
                    else:
                        home_base = random.choice([+105, +110, +120, +150, +180])
                
                base_market_odds[market_key] = {
                    "home": home_base,
                    "away": away_base,
                }
            elif market_key == "spreads":
                spread = random.choice([-3.5, -4.0, -5.5, -6.0, -7.5, 3.5, 4.0, 5.5, 6.0, 7.5])
                base_market_odds[market_key] = {
                    "spread": spread,
                }
            elif market_key == "totals":
                total = random.choice([45.5, 46.0, 47.5, 48.0, 220.5, 221.0, 225.5, 230.0])
                base_market_odds[market_key] = {
                    "total": total,
                }
        
        # Generate bookmaker data
        # Rule: Novig gets the best odds for each side (same side)
        # Other books get worse odds for the same side
        # Post-processing will ensure hedge EV is never positive
        bookmakers = []
        common_odds = [-200, -180, -160, -150, -140, -130, -120, -115, -110, -105,
                      +105, +110, +115, +120, +130, +140, +150, +160, +180, +200, +220, +250]
        
        # First, generate Novig odds (best for same side)
        novig_bookmaker = None
        for book_key in bookmaker_keys:
            is_novig = book_key.lower() == "novig"
            if not is_novig:
                continue
            
            markets_data = []
            for market_key in market_list:
                outcomes = []
                
                if market_key == "h2h":
                    base_home = base_market_odds[market_key]["home"]
                    base_away = base_market_odds[market_key]["away"]
                    # Novig: best odds (use base odds directly)
                    outcomes = [
                        {"name": home, "price": base_home},
                        {"name": away, "price": base_away},
                    ]
                elif market_key == "spreads":
                    spread = base_market_odds[market_key]["spread"]
                    # Novig: -105 (best)
                    outcomes = [
                        {"name": home, "price": -105, "point": spread},
                        {"name": away, "price": -105, "point": -spread},
                    ]
                elif market_key == "totals":
                    total = base_market_odds[market_key]["total"]
                    # Novig: -105 (best)
                    outcomes = [
                        {"name": f"Over {total}", "price": -105, "point": total},
                        {"name": f"Under {total}", "price": -105, "point": total},
                    ]
                elif market_key.startswith("player_"):
                    # Player props: generate Over/Under outcomes for a random player
                    # This will be handled in the extended dummy data function
                    pass
                
                if outcomes:
                    markets_data.append({
                        "key": market_key,
                        "outcomes": outcomes,
                    })
            
            if markets_data:
                novig_bookmaker = {
                    "key": book_key,
                    "title": book_key.title(),
                    "markets": markets_data,
                }
                bookmakers.append(novig_bookmaker)
                break
        
        # Then generate other books' odds (worse than Novig for same side)
        for book_key in bookmaker_keys:
            is_novig = book_key.lower() == "novig"
            if is_novig:
                continue
            
            markets_data = []
            for market_key in market_list:
                outcomes = []
                
                if market_key == "h2h":
                    base_home = base_market_odds[market_key]["home"]
                    base_away = base_market_odds[market_key]["away"]
                    
                    # Other books: MUCH worse odds to prevent arbitrage
                    # Apply significant vig to ensure no arbitrage opportunities even before vig adjustment
                    # For positive odds: reduce significantly (30-50 points)
                    # For negative odds: make much more negative (30-50 points)
                    if base_home > 0:
                        home_odds = max(base_home - random.choice([30, 40, 50, 60]), 100)
                    else:
                        home_odds = base_home - random.choice([30, 40, 50, 60])  # More negative = worse
                    
                    if base_away > 0:
                        away_odds = max(base_away - random.choice([30, 40, 50, 60]), 100)
                    else:
                        away_odds = base_away - random.choice([30, 40, 50, 60])  # More negative = worse
                    
                    # Round to common odds values, ensuring they're worse than Novig
                    home_odds = min(common_odds, key=lambda x: abs(x - home_odds))
                    away_odds = min(common_odds, key=lambda x: abs(x - away_odds))
                    
                    # Ensure they're actually worse than Novig's odds
                    if base_home > 0 and home_odds >= base_home:
                        home_odds = max([x for x in common_odds if x > 0 and x < base_home], default=100)
                    elif base_home < 0 and home_odds >= base_home:  # For negative, >= means less negative (better)
                        home_odds = min([x for x in common_odds if x < base_home], default=base_home - 30)
                    
                    if base_away > 0 and away_odds >= base_away:
                        away_odds = max([x for x in common_odds if x > 0 and x < base_away], default=100)
                    elif base_away < 0 and away_odds >= base_away:  # For negative, >= means less negative (better)
                        away_odds = min([x for x in common_odds if x < base_away], default=base_away - 30)
                    
                    outcomes = [
                        {"name": home, "price": home_odds},
                        {"name": away, "price": away_odds},
                    ]
                elif market_key == "spreads":
                    spread = base_market_odds[market_key]["spread"]
                    # Others: -110 to -115 (worse than Novig's -105)
                    home_odds = random.choice([-110, -115])
                    away_odds = random.choice([-110, -115])
                    
                    outcomes = [
                        {"name": home, "price": home_odds, "point": spread},
                        {"name": away, "price": away_odds, "point": -spread},
                    ]
                elif market_key == "totals":
                    total = base_market_odds[market_key]["total"]
                    # Others: -110 to -115 (worse than Novig's -105)
                    over_odds = random.choice([-110, -115])
                    under_odds = random.choice([-110, -115])
                    
                    outcomes = [
                        {"name": f"Over {total}", "price": over_odds, "point": total},
                        {"name": f"Under {total}", "price": under_odds, "point": total},
                    ]
                elif market_key.startswith("player_"):
                    # Player props: generate Over/Under outcomes for a random player
                    # This will be handled in the extended dummy data function
                    pass
                
                if outcomes:
                    markets_data.append({
                        "key": market_key,
                        "outcomes": outcomes,
                    })
            
            if markets_data:
                bookmakers.append({
                    "key": book_key,
                    "title": book_key.title(),
                    "markets": markets_data,
                })
        
        # Post-process: Ensure no positive EV hedges when comparing other books against Novig
        # Adjust Novig's opposite-side odds to ensure hedge EV <= 0
        # But keep Novig's same-side odds better than other books
        def is_better_odds(odds1: int, odds2: int) -> bool:
            """Check if odds1 is better than or equal to odds2"""
            if odds1 > 0 and odds2 > 0:
                return odds1 >= odds2
            elif odds1 < 0 and odds2 < 0:
                return odds1 >= odds2  # -105 >= -110
            else:
                # Mixed signs - positive is always better than negative
                return odds1 > 0
        
        def ensure_no_positive_hedge(other_side_odds: int, novig_opposite_odds: int, other_opposite_odds: int) -> tuple[int, int]:
            """Adjust novig_opposite_odds to ensure hedge EV <= 0, while keeping it >= other_opposite_odds
            Returns: (adjusted_novig_opposite_odds, adjusted_other_opposite_odds)
            If other_opposite_odds needs adjustment, it's returned; otherwise same value is returned.
            """
            dec_other_side = american_to_decimal(other_side_odds)
            dec_novig_opposite = american_to_decimal(novig_opposite_odds)
            inv_sum = 1.0 / dec_other_side + 1.0 / dec_novig_opposite
            
            if inv_sum >= 1.0:
                # Already no positive hedge, but ensure Novig is >= other book for same side
                if is_better_odds(novig_opposite_odds, other_opposite_odds):
                    return (novig_opposite_odds, other_opposite_odds)
                else:
                    # Novig is worse than other book for same side - make other book worse
                    if other_opposite_odds > 0:
                        adjusted_other = max(other_opposite_odds - random.choice([5, 10]), 100)
                    else:
                        adjusted_other = other_opposite_odds - random.choice([5, 10])
                    adjusted_other = min(common_odds, key=lambda x: abs(x - adjusted_other))
                    return (novig_opposite_odds, adjusted_other)
            
            # Calculate max allowed decimal for Novig opposite to ensure inv_sum >= 1.0
            max_dec = 1.0 / (1.0 - 1.0 / dec_other_side) if (1.0 - 1.0 / dec_other_side) > 0 else float('inf')
            if max_dec >= float('inf'):
                return (novig_opposite_odds, other_opposite_odds)
            
            max_american = decimal_to_american(max_dec)
            
            # Adjust Novig opposite to satisfy hedge constraint (priority: hedge EV <= 0)
            if novig_opposite_odds > 0:
                # For positive odds, smaller is worse - use min to ensure hedge EV <= 0
                adjusted_novig = min(max_american, novig_opposite_odds)
            else:
                # For negative odds, more negative is worse - use min to ensure hedge EV <= 0
                # min(-110, -105) = -110 (more negative = worse odds)
                adjusted_novig = min(max_american, novig_opposite_odds)
            
            # Now ensure Novig opposite is >= other book opposite (same side comparison)
            # If adjusted_novig doesn't satisfy this, we need to make other book's opposite side worse
            adjusted_other = other_opposite_odds
            if not is_better_odds(adjusted_novig, other_opposite_odds):
                # Can't satisfy both constraints - make other book's opposite side worse
                # Make it worse than adjusted_novig to ensure Novig is better
                if adjusted_novig > 0:
                    # For positive odds, smaller is worse
                    adjusted_other = max(adjusted_novig - 5, 100)
                else:
                    # For negative odds, more negative is worse
                    adjusted_other = adjusted_novig - 5
                adjusted_other = min(common_odds, key=lambda x: abs(x - adjusted_other))
            
            # Round to common odds, but ensure it doesn't exceed max_american (hedge EV constraint)
            rounded_novig = min(common_odds, key=lambda x: abs(x - adjusted_novig))
            # Ensure rounded value still satisfies hedge EV constraint
            if adjusted_novig > 0:
                # For positive odds, ensure rounded value <= max_american
                adjusted_novig = min(rounded_novig, max_american)
            else:
                # For negative odds, ensure rounded value <= max_american (more negative)
                adjusted_novig = min(rounded_novig, max_american)
            return (adjusted_novig, adjusted_other)
        
        if novig_bookmaker:
            other_bookmakers = [b for b in bookmakers if b["key"].lower() != "novig"]
            
            for market_key in market_list:
                novig_market = next((m for m in novig_bookmaker["markets"] if m["key"] == market_key), None)
                if not novig_market:
                    continue
                
                if market_key == "h2h":
                    novig_home_outcome = next((o for o in novig_market["outcomes"] if o["name"] == home), None)
                    novig_away_outcome = next((o for o in novig_market["outcomes"] if o["name"] == away), None)
                    
                    if not (novig_home_outcome and novig_away_outcome):
                        continue
                    
                    novig_home_odds = novig_home_outcome["price"]
                    novig_away_odds = novig_away_outcome["price"]
                    
                    # Check each other book and adjust Novig's opposite side if needed
                    for other_book in other_bookmakers:
                        other_market = next((m for m in other_book["markets"] if m["key"] == "h2h"), None)
                        if not other_market:
                            continue
                        
                        other_home_outcome = next((o for o in other_market["outcomes"] if o["name"] == home), None)
                        other_away_outcome = next((o for o in other_market["outcomes"] if o["name"] == away), None)
                        
                        if not (other_home_outcome and other_away_outcome):
                            continue
                        
                        other_home_odds = other_home_outcome["price"]
                        other_away_odds = other_away_outcome["price"]
                        
                        # Check and adjust hedge: bet home at other book, hedge away at Novig
                        adjusted_novig_away, adjusted_other_away = ensure_no_positive_hedge(other_home_odds, novig_away_odds, other_away_odds)
                        if adjusted_novig_away != novig_away_odds:
                            novig_away_odds = adjusted_novig_away
                            novig_away_outcome["price"] = novig_away_odds
                        if adjusted_other_away != other_away_odds:
                            other_away_odds = adjusted_other_away
                            other_away_outcome["price"] = other_away_odds
                        
                        # Check and adjust hedge: bet away at other book, hedge home at Novig
                        adjusted_novig_home, adjusted_other_home = ensure_no_positive_hedge(other_away_odds, novig_home_odds, other_home_odds)
                        if adjusted_novig_home != novig_home_odds:
                            novig_home_odds = adjusted_novig_home
                            novig_home_outcome["price"] = novig_home_odds
                        if adjusted_other_home != other_home_odds:
                            other_home_odds = adjusted_other_home
                            other_home_outcome["price"] = other_home_odds
                
                elif market_key == "spreads":
                    # For spreads, both sides have the same point but opposite signs
                    # Check hedge: bet home spread at other book, hedge away spread at Novig
                    novig_home_outcome = next((o for o in novig_market["outcomes"] if o["name"] == home), None)
                    novig_away_outcome = next((o for o in novig_market["outcomes"] if o["name"] == away), None)
                    
                    if not (novig_home_outcome and novig_away_outcome):
                        continue
                    
                    novig_home_odds = novig_home_outcome["price"]
                    novig_away_odds = novig_away_outcome["price"]
                    
                    for other_book in other_bookmakers:
                        other_market = next((m for m in other_book["markets"] if m["key"] == "spreads"), None)
                        if not other_market:
                            continue
                        
                        other_home_outcome = next((o for o in other_market["outcomes"] if o["name"] == home), None)
                        other_away_outcome = next((o for o in other_market["outcomes"] if o["name"] == away), None)
                        
                        if not (other_home_outcome and other_away_outcome):
                            continue
                        
                        other_home_odds = other_home_outcome["price"]
                        other_away_odds = other_away_outcome["price"]
                        
                        # Check and adjust hedge: bet home spread at other book, hedge away spread at Novig
                        adjusted_novig_away, adjusted_other_away = ensure_no_positive_hedge(other_home_odds, novig_away_odds, other_away_odds)
                        if adjusted_novig_away != novig_away_odds:
                            novig_away_odds = adjusted_novig_away
                            novig_away_outcome["price"] = novig_away_odds
                        if adjusted_other_away != other_away_odds:
                            other_away_odds = adjusted_other_away
                            other_away_outcome["price"] = other_away_odds
                        
                        # Check and adjust hedge: bet away spread at other book, hedge home spread at Novig
                        adjusted_novig_home, adjusted_other_home = ensure_no_positive_hedge(other_away_odds, novig_home_odds, other_home_odds)
                        if adjusted_novig_home != novig_home_odds:
                            novig_home_odds = adjusted_novig_home
                            novig_home_outcome["price"] = novig_home_odds
                        if adjusted_other_home != other_home_odds:
                            other_home_odds = adjusted_other_home
                            other_home_outcome["price"] = other_home_odds
                
                elif market_key == "totals":
                    # For totals, check hedge: bet over at other book, hedge under at Novig (and vice versa)
                    novig_over_outcome = next((o for o in novig_market["outcomes"] if "Over" in o["name"]), None)
                    novig_under_outcome = next((o for o in novig_market["outcomes"] if "Under" in o["name"]), None)
                    
                    if not (novig_over_outcome and novig_under_outcome):
                        continue
                    
                    novig_over_odds = novig_over_outcome["price"]
                    novig_under_odds = novig_under_outcome["price"]
                    
                    for other_book in other_bookmakers:
                        other_market = next((m for m in other_book["markets"] if m["key"] == "totals"), None)
                        if not other_market:
                            continue
                        
                        other_over_outcome = next((o for o in other_market["outcomes"] if "Over" in o["name"]), None)
                        other_under_outcome = next((o for o in other_market["outcomes"] if "Under" in o["name"]), None)
                        
                        if not (other_over_outcome and other_under_outcome):
                            continue
                        
                        other_over_odds = other_over_outcome["price"]
                        other_under_odds = other_under_outcome["price"]
                        
                        # Check and adjust hedge: bet over at other book, hedge under at Novig
                        adjusted_novig_under, adjusted_other_under = ensure_no_positive_hedge(other_over_odds, novig_under_odds, other_under_odds)
                        if adjusted_novig_under != novig_under_odds:
                            novig_under_odds = adjusted_novig_under
                            novig_under_outcome["price"] = novig_under_odds
                        if adjusted_other_under != other_under_odds:
                            other_under_odds = adjusted_other_under
                            other_under_outcome["price"] = other_under_odds
                        
                        # Check and adjust hedge: bet under at other book, hedge over at Novig
                        adjusted_novig_over, adjusted_other_over = ensure_no_positive_hedge(other_under_odds, novig_over_odds, other_over_odds)
                        if adjusted_novig_over != novig_over_odds:
                            novig_over_odds = adjusted_novig_over
                            novig_over_outcome["price"] = novig_over_odds
                        if adjusted_other_over != other_over_odds:
                            other_over_odds = adjusted_other_over
                            other_over_outcome["price"] = other_over_odds
        
        events.append({
            "id": event_id,
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
    common_odds = [-200, -180, -160, -150, -140, -130, -120, -115, -110, -105,
                  +105, +110, +115, +120, +130, +140, +150, +160, +180, +200, +220, +250]
    
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


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
    use_dummy_data: bool = False,
) -> List[Dict[str, Any]]:
    """
    Core call to /v4/sports/{sport_key}/odds.
    If use_dummy_data is True, returns mock data instead of calling the API.
    """
    if use_dummy_data:
        return generate_dummy_odds_data(sport_key, markets, bookmaker_keys)
    
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "bookmakers": ",".join(bookmaker_keys),
    }

    url = f"{BASE_URL}/sports/{sport_key}/odds"
    response = requests.get(url, params=params, timeout=15)
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Error from The Odds API: {response.status_code}, {response.text}",
        )
    return response.json()


def american_to_decimal(odds: int) -> float:
    """
    Convert American odds to decimal odds.
    """
    if odds > 0:
        return 1.0 + odds / 100.0
    else:
        return 1.0 + 100.0 / abs(odds)


def decimal_to_american(decimal: float) -> int:
    """
    Convert decimal odds to American odds.
    """
    if decimal >= 2.0:
        return int((decimal - 1.0) * 100)
    else:
        return int(-100.0 / (decimal - 1.0))


def apply_vig_adjustment(odds: int, bookmaker_key: str) -> int:
    """
    Apply vig adjustment to odds to make them less favorable (reduce 0% hedge opportunities).
    High vig levels to reflect reality: arbitrage bets are extremely rare due to vig.
    - Fliff: 30% vig (highest)
    - DraftKings: 20% vig
    - FanDuel: 20% vig
    
    Args:
        odds: American odds
        bookmaker_key: The bookmaker key (e.g., "draftkings", "fanduel", "fliff")
    
    Returns:
        Adjusted American odds (less favorable)
    """
    if odds is None:
        return odds
    
    # Define vig percentages by book (higher = more vig, less favorable odds)
    # Set to realistic high vig levels to make arbitrage opportunities very rare
    # In reality, vig makes arbitrage bets extremely difficult to find
    vig_percentages = {
        "fliff": 0.30,      # 30% vig for Fliff (highest - makes arb extremely rare)
        "draftkings": 0.20,  # 20% vig for DraftKings
        "fanduel": 0.20,    # 20% vig for FanDuel
    }
    
    vig_pct = vig_percentages.get(bookmaker_key.lower(), 0.0)
    if vig_pct == 0.0:
        # No adjustment for other books
        return odds
    
    # Convert to decimal odds
    dec_odds = american_to_decimal(odds)
    
    # Apply vig: reduce the decimal odds by the vig percentage
    # This makes the odds less favorable (higher implied probability)
    # Add a small additional buffer (1%) to prevent exactly 0% margins and ensure rounding doesn't undo the effect
    buffer = 0.01  # 1% additional buffer to ensure odds are always significantly worse
    adjusted_dec = dec_odds * (1.0 - vig_pct - buffer)
    
    # Convert back to American odds
    adjusted_american = decimal_to_american(adjusted_dec)
    
    # CRITICAL FIX: If original odds were positive, ensure adjusted odds stay positive
    # High vig can cause positive odds to drop below 2.0 decimal, making them negative
    if odds > 0:
        if adjusted_american <= 0:
            # Force it to be positive but worse than original
            # Use a minimum positive value that's worse than original
            adjusted_american = max(100, odds - 50)  # At least 50 points worse, minimum +100
        # Also ensure adjusted is always worse (less positive) than original
        if adjusted_american >= odds:
            adjusted_american = max(100, odds - 50)
    
    # Round to nearest common odds value to keep it realistic
    # Use a more comprehensive list that includes more granular values
    common_odds = [
        -10000, -5000, -2500, -2000, -1500, -1200, -1000, -900, -800, -700, -600, -550,
        -500, -475, -450, -425, -400, -375, -350, -325, -300, -275, -250, -225, -200,
        -190, -180, -170, -160, -150, -140, -130, -120, -115, -110, -105, -102,
        100, 102, 105, 110, 115, 120, 130, 140, 150, 160, 170, 180, 190,
        200, 225, 250, 275, 300, 325, 350, 375, 400, 425, 450, 475, 500,
        550, 600, 700, 800, 900, 1000, 1200, 1500, 2000, 2500, 5000, 10000
    ]
    
    # Find closest common odds value that makes odds worse (not better)
    # CRITICAL: For negative odds, "worse" means MORE negative (e.g., -200 is worse than -130)
    # For positive odds, "worse" means LESS positive (e.g., +100 is worse than +150)
    if odds > 0:
        # For positive odds, find the closest value that is < adjusted_american (strictly worse)
        # CRITICAL: Only consider positive values in common_odds
        # Filter to only positive values that are strictly worse than adjusted_american and original
        positive_common_odds = [x for x in common_odds if x > 0]
        worse_options = [x for x in positive_common_odds if x < adjusted_american and x < odds]
        if worse_options:
            closest = max(worse_options)  # Closest but still worse
        else:
            # If no worse option found, use the adjusted value directly but ensure it's worse and positive
            closest = max(100, int(adjusted_american))  # Ensure it's at least +100
            # Ensure it's strictly worse than original
            if closest >= odds:
                # Find the next worse positive value
                worse_values = [x for x in positive_common_odds if x < odds]
                if worse_values:
                    closest = max(worse_values)
                else:
                    closest = max(100, odds - 50)  # At least make it significantly worse, minimum +100
        return closest
    else:
        # For negative odds, "worse" means MORE negative (e.g., -200 is worse than -130)
        # So we need values that are < adjusted_american (more negative)
        # adjusted_american should be more negative than original odds
        worse_options = [x for x in common_odds if x < adjusted_american and x < odds]
        if worse_options:
            # Find the value closest to adjusted_american but still more negative than original
            closest = max(worse_options)  # Most negative (worst) option that's still valid
        else:
            # If no worse option found, use the adjusted value directly but ensure it's worse
            closest = int(adjusted_american)
            # Ensure it's strictly worse than original (more negative)
            if closest >= odds:  # If closest is less negative (better) than original
                # Find the next worse value (more negative)
                worse_values = [x for x in common_odds if x < odds]
                if worse_values:
                    closest = max(worse_values)  # Most negative (worst) option
                else:
                    closest = odds - 10  # At least make it significantly worse (more negative)
        return closest


def american_to_prob(odds: int) -> float:
    """
    Convert American odds to implied probability.
    """
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return abs(odds) / (abs(odds) + 100.0)


def estimate_ev_percent(book_odds: int, sharp_odds: int) -> float:
    """
    Approximate EV% using:
      EV% ~ (decimal_book * sharp_prob - 1) * 100
    where sharp_prob is implied probability from Novig, treated as "true".
    """
    book_dec = american_to_decimal(book_odds)
    sharp_prob = american_to_prob(sharp_odds)
    ev = book_dec * sharp_prob - 1.0
    return ev * 100.0


def points_match(
    book_point: Optional[float],
    novig_point: Optional[float],
    allow_half_point_flex: bool,
) -> bool:
    """Determine if two points should be treated as matching.

    For most markets we require an exact match (including both being ``None``).
    For spreads/totals, The Odds API occasionally publishes a 0.5-point
    difference between Novig and the target book; when ``allow_half_point_flex``
    is True we still consider those to be a match.
    """

    if book_point is None or novig_point is None:
        return book_point == novig_point

    diff = abs(book_point - novig_point)
    if diff < 1e-9:
        return True

    if allow_half_point_flex and diff <= 0.5 + 1e-9:
        return True

    return False


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
            
            reverse_display_name = novig_reverse_name
            if is_player_prop and other_compare and other_compare.get("description"):
                reverse_desc = other_compare.get("description")
                reverse_display_name = f"{reverse_desc} {novig_reverse_name}" if novig_reverse_name else None

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


def format_start_time_est(iso_str: str) -> str:
    """Convert an ISO UTC time string into an easy-to-read EST label.

    Example output: "Thu, Nov 20, 3:30 PM ET".
    If parsing fails, returns the original string.
    """
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        # Format: "Thu, Nov 20, 3:30 PM ET" (more readable than "Thu 11/20 03:30 PM ET")
        # Use %I for hour (01-12) and remove leading zero manually for cross-platform compatibility
        formatted = dt_et.strftime("%a, %b %d, %I:%M %p ET")
        # Remove leading zero from hour (e.g., " 03:" -> " 3:")
        if formatted[8:10] == " 0" and formatted[10].isdigit():
            formatted = formatted[:8] + " " + formatted[10:]
        return formatted
    except Exception:
        return iso_str


def choose_three_leg_parlay(plays: List[ValuePlayOutcome], target_book: str) -> Optional[Dict[str, Any]]:
    """
    Very simple 3-leg high-EV parlay suggestion:
      - take the top +EV plays (ev_percent)
      - ensure all 3 legs come from different events
    """
    if len(plays) < 3:
        return None

    sorted_plays = sorted(plays, key=lambda p: p.ev_percent, reverse=True)

    chosen: List[ValuePlayOutcome] = []
    used_event_ids: Set[str] = set()

    for p in sorted_plays:
        if p.event_id in used_event_ids:
            continue
        chosen.append(p)
        used_event_ids.add(p.event_id)
        if len(chosen) == 3:
            break

    if len(chosen) < 3:
        return None

    decimal_odds_list = [american_to_decimal(p.book_price) for p in chosen]
    combined_decimal = 1.0
    for d in decimal_odds_list:
        combined_decimal *= d

    sharp_probs = [american_to_prob(p.novig_price) for p in chosen]
    combined_sharp_prob = 1.0
    for sp in sharp_probs:
        combined_sharp_prob *= sp

    parlay_ev = combined_decimal * combined_sharp_prob - 1.0
    parlay_ev_percent = parlay_ev * 100.0

    return {
        "target_book": target_book,
        "legs": [
            {
                "event_id": p.event_id,
                "matchup": p.matchup,
                "outcome_name": p.outcome_name,
                "point": p.point,
                "book_price": p.book_price,
                "novig_price": p.novig_price,
                "ev_percent": p.ev_percent,
            }
            for p in chosen
        ],
        "combined_decimal_odds": combined_decimal,
        "combined_sharp_prob": combined_sharp_prob,
        "estimated_parlay_ev_percent": parlay_ev_percent,
        "approx_parlay_decimal_odds": combined_decimal,
        "approx_parlay_ev_percent": parlay_ev_percent,
    }


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

        events = fetch_odds(
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
    and market, returning the best value plays and an optional 3-leg parlay suggestion.

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

    events = fetch_odds(
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

    sgp_suggestion = None
    if payload.include_sgp and top_plays:
        # SGP still uses same-side EV ordering internally
        sgp_suggestion = choose_three_leg_parlay(top_plays, target_book)

    return ValuePlaysResponse(
        target_book=target_book,
        compare_book=compare_book,
        market=market_key,
        plays=top_plays,
        sgp_suggestion=sgp_suggestion,
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
                events = fetch_odds(
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
        sgp_suggestion=None,
    )


@app.get("/api/widget-key")
def get_widget_key():
    """
    Get the widget API key from environment variable.
    Returns the key if set, or null if not configured.
    """
    key = get_widget_api_key()
    return {"key": key}


@app.get("/api/widget-display-url")
def get_widget_display_url():
    """
    Get the URL for the widget display page with the widget API key included.
    Returns the URL if the key is configured, otherwise returns an error.
    """
    widget_key = get_widget_api_key()
    if not widget_key:
        raise HTTPException(
            status_code=400,
            detail="Widget API key not configured. Set THE_ODDS_WIDGET_API_KEY environment variable.",
        )
    
    # Return URL with widget key as query parameter
    display_url = f"/widget-display.html?key={widget_key}"
    return {"url": display_url}


@app.get("/api/widget-url")
def generate_widget_url(
    sport: str,
    bookmaker: str,
    odds_format: str = "american",
    markets: str = "h2h,spreads,totals",
    market_names: Optional[str] = None,
):
    """
    Generate a widget URL with the access key embedded.
    
    Parameters:
    - sport: Sport key (e.g., "americanfootball_nfl")
    - bookmaker: Bookmaker key (e.g., "draftkings")
    - odds_format: "american" or "decimal" (default: "american")
    - markets: Comma-separated markets (default: "h2h,spreads,totals")
    - market_names: Optional comma-separated market:label pairs (e.g., "h2h:Moneyline,spreads:Spread")
    """
    widget_key = get_widget_api_key()
    if not widget_key:
        raise HTTPException(
            status_code=400,
            detail="Widget API key not configured. Set THE_ODDS_WIDGET_API_KEY environment variable.",
        )
    
    base_url = f"https://widget.the-odds-api.com/v1/sports/{sport}/events/"
    params = {
        "accessKey": widget_key,
        "bookmakerKeys": bookmaker,
        "oddsFormat": odds_format,
        "markets": markets,
    }
    
    if market_names:
        params["marketNames"] = market_names
    
    query_string = "&".join([f"{k}={v}" for k, v in params.items()])
    widget_url = f"{base_url}?{query_string}"
    
    return {"url": widget_url}


# Static frontend (index.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
