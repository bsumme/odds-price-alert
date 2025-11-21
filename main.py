import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Set, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
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
    book_prices: Dict[str, Optional[int]] = Field(default_factory=dict)
    

class ValuePlaysResponse(BaseModel):
    target_book: str
    market: str
    plays: List[ValuePlayOutcome]
    sgp_suggestion: Optional[Dict[str, Any]] = None  # holds 3-leg SGP suggestion if requested


class ValuePlaysRequest(BaseModel):
    """
    Request body for /api/value-plays:
      - sport_key: e.g. "basketball_nba"
      - target_book: e.g. "draftkings"
      - market: "h2h", "spreads", "totals", or "player_points"
      - include_sgp: whether to build a naive 3-leg parlay from the top plays
    """
    sport_key: str
    target_book: str
    market: str
    include_sgp: bool = False
    max_results: Optional[int] = None


BOOK_LABELS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "novig": "Novig",
    "fliff": "Fliff",
    # add more as needed
}

# Books whose prices we want to surface alongside the target book in value finder
VALUE_PLAY_DISPLAY_BOOKS = ["draftkings", "fanduel", "fliff"]

def get_api_key() -> str:
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing THE_ODDS_API_KEY environment variable. "
            "Set it in Windows Environment Variables and restart."
        )
    return api_key


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


def fetch_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    markets: str,
    bookmaker_keys: List[str],
) -> List[Dict[str, Any]]:
    """
    Core call to /v4/sports/{sport_key}/odds.
    """
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

def _canonical_outcome_name(name: Optional[str]) -> Optional[str]:
    """Normalize an outcome name for looser cross-book comparisons."""

    if name is None:
        return None

    return name.lower().replace(".", "").replace("'", "").strip()


def find_best_matching_outcome(
    *,
    outcomes: List[Dict[str, Any]],
    name: str,
    point: Optional[float],
    allow_half_point_flex: bool,
    opposite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Return the outcome that best matches a book outcome.

    When ``opposite`` is True, search for an outcome with a different name (the
    other side of the bet). Preference is given to exact point matches, but for
    spreads/totals we will also accept lines that differ by up to 0.5.
    """

    best: Optional[Dict[str, Any]] = None
    best_diff: float = float("inf")

    for candidate in outcomes:
        candidate_name = candidate.get("name")
        if opposite:
            if candidate_name == name:
                continue
        elif candidate_name != name:
            continue

        candidate_point = candidate.get("point", None)
        if not points_match(point, candidate_point, allow_half_point_flex):
            continue

        diff = abs((point or 0.0) - (candidate_point or 0.0))
        if diff < best_diff:
            best = candidate
            best_diff = diff

            # Exact point match is the best we can do
            if diff < 1e-9:
                break

    return best
def extract_valid_outcomes(market: Dict[str, Any]) -> List[Dict[str, Any]]:
    outcomes: List[Dict[str, Any]] = []
    for o in market.get("outcomes", []):
        name = o.get("name")
        price = o.get("price")
        point = o.get("point", None)
        if name is None or price is None:
            continue
        if abs(price) >= MAX_VALID_AMERICAN_ODDS:
            # Skip absurd values like -100000
            continue
        outcomes.append({"name": name, "price": price, "point": point})
    return outcomes


def normalize_outcomes(market: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract clean outcomes from a bookmaker market."""

    if not market:
        return []

    cleaned: List[Dict[str, Any]] = []
    for o in market.get("outcomes", []):
        name = o.get("name")
        price = o.get("price")
        point = o.get("point", None)
        if name is None or price is None:
            continue
        if abs(price) >= MAX_VALID_AMERICAN_ODDS:
            # Skip absurd values like -100000
            continue
        cleaned.append({"name": name, "price": price, "point": point})

    return cleaned


def collect_value_plays(
    events: List[Dict[str, Any]],
    market_key: str,
    target_book: str,
    display_books: List[str],
) -> List[ValuePlayOutcome]:
    """
    Scan all events and outcomes in the given market, comparing target_book vs Novig.
    Only considers outcomes where:
      - both books have a price,
      - and for spreads/totals/props, the points match (within 0.5 for spreads/totals).

    Also:
      - Finds the *other* Novig outcome (matching or close point, different name)
        and exposes its true odds + team name as "novig_reverse_*" (hedge side).
      - Detects 2-way arbitrage: back this side at the target book, back the
        opposite side at Novig.
    """
    plays: List[ValuePlayOutcome] = []

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        start_time = event.get("commence_time")
        event_id = event.get("id", "")

        matchup = f"{away} @ {home}" if home and away else ""

        novig_market = None
        book_market = None
        markets_by_book: Dict[str, Dict[str, Any]] = {}

        for bookmaker in event.get("bookmakers", []):
            key = bookmaker.get("key")
            market = next(
                (m for m in bookmaker.get("markets", []) if m.get("key") == market_key),
                None,
            )
            if not market:
                continue

            if key == "novig":
                novig_market = market
            elif key == target_book:
                book_market = market

            if key in display_books:
                markets_by_book[key] = market

        if not novig_market or not book_market:
            continue

        # Allow 0.5-point flex for both spreads and totals (Odds API sometimes
        # differs by 0.5 between books).
        allow_half_point_flex = market_key in ("totals", "spreads")

        novig_outcomes = extract_valid_outcomes(novig_market)
        book_outcomes = extract_valid_outcomes(book_market)

        if not novig_outcomes:
            continue

        for o in book_outcomes:
            name = o.get("name")
            price = o.get("price")
            point = o.get("point", None)

            matching_novig = find_best_matching_outcome(
                outcomes=novig_outcomes,
                name=name,
                point=point,
                allow_half_point_flex=allow_half_point_flex,
            )
            if matching_novig is None:
                continue

            novig_price = matching_novig["price"]
            ev_pct = estimate_ev_percent(book_odds=price, sharp_odds=novig_price)

            # Find the *other* Novig side (hedge side) with matching/close point
            other_novig = find_best_matching_outcome(
                outcomes=novig_outcomes,
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

            if other_novig is not None:
                novig_reverse_name = other_novig.get("name")
                novig_reverse_price = other_novig.get("price")
                hedge_ev_percent = estimate_ev_percent(
                    book_odds=price, sharp_odds=novig_reverse_price
                )

                # 2-way arb math:
                #  - back this side at target_book (book_price)
                #  - back opposite side at Novig (novig_reverse_price)
                d_book = american_to_decimal(price)
                d_novig_other = american_to_decimal(novig_reverse_price)
                inv_sum = 1.0 / d_book + 1.0 / d_novig_other
                # Hedge margin: 0% ~ fair (e.g. -125 / +125), >0% profitable arb, <0% losing hedge
                arb_margin_percent = (1.0 - inv_sum) * 100.0
                if arb_margin_percent > 0:
                    is_arb = True


            book_prices: Dict[str, Optional[int]] = {}
            for book_key in display_books:
                market_for_book = markets_by_book.get(book_key)
                if not market_for_book:
                    book_prices[book_key] = None
                    continue

                outcomes_for_book = extract_valid_outcomes(market_for_book)
                match = find_best_matching_outcome(
                    outcomes=outcomes_for_book,
                    name=name,
                    point=point,
                    allow_half_point_flex=allow_half_point_flex,
                )
                book_prices[book_key] = match.get("price") if match else None

            plays.append(
                ValuePlayOutcome(
                    event_id=event_id,
                    matchup=matchup,
                    start_time=start_time,
                    outcome_name=name,
                    point=point,
                    novig_price=novig_price,
                    novig_reverse_name=novig_reverse_name,
                    novig_reverse_price=novig_reverse_price,
                    book_price=price,
                    ev_percent=ev_pct,
                    hedge_ev_percent=hedge_ev_percent,
                    is_arbitrage=is_arb,
                    arb_margin_percent=arb_margin_percent,
                    book_prices=book_prices,
                )
            )

    return plays

def format_start_time_est(iso_str: str) -> str:
    """Convert an ISO UTC time string into an easy-to-read EST label.

    Example output: "Thu 11/20 03:30 PM ET".
    If parsing fails, returns the original string.
    """
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        return dt_et.strftime("%a %m/%d %I:%M %p ET")
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
    Compare a target sportsbook to Novig (treated as "sharp") for a given sport
    and market, returning the best value plays and an optional 3-leg parlay suggestion.

    Sorting:
      - Primary sort is by hedge opportunity using arb_margin_percent:
          arb_margin_percent = (1 - (1/dec_book + 1/dec_novig_opposite)) * 100
        where dec_book is the decimal odds at the target book, and
        dec_novig_opposite is the decimal odds of the Novig *opposite* side.
      - A pair like -125 / +125 gives ~0% (fair hedge).
      - Positive values indicate 2-way arbitrage (profitable hedge),
        negative values indicate a losing hedge.
      - Plays with no Novig opposite side are pushed to the bottom.
    """
    target_book = payload.target_book
    market_key = payload.market

    if target_book == "novig":
        raise HTTPException(
            status_code=400,
            detail="Target book cannot be Novig (Novig is the sharp reference).",
        )

    try:
        api_key = get_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    display_books = sorted(set(VALUE_PLAY_DISPLAY_BOOKS + [target_book]))
    bookmaker_keys = sorted(set([target_book, "novig"] + VALUE_PLAY_DISPLAY_BOOKS))
    regions = compute_regions_for_books(bookmaker_keys)

    events = fetch_odds(
        api_key=api_key,
        sport_key=payload.sport_key,
        regions=regions,
        markets=market_key,
        bookmaker_keys=bookmaker_keys,
    )

    raw_plays = collect_value_plays(events, market_key, target_book, display_books)

    # Filter out games that started a long time ago (keep upcoming / recent only)
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=12)
    filtered_plays: List[ValuePlayOutcome] = []
    for p in raw_plays:
        if not p.start_time:
            filtered_plays.append(p)
            continue
        try:
            dt = datetime.fromisoformat(p.start_time.replace("Z", "+00:00"))
        except Exception:
            filtered_plays.append(p)
            continue
        if dt >= cutoff:
            filtered_plays.append(p)

    # Convert start_time into an easy-to-read EST string for display
    for p in filtered_plays:
        if p.start_time:
            p.start_time = format_start_time_est(p.start_time)



    # Sort primarily by hedge opportunity (arb_margin_percent) descending.
    # Plays with no Novig opposite side get pushed to the bottom.
    def hedge_sort_key(play: ValuePlayOutcome) -> float:
        """
        Sort plays by hedge margin first. Plays without an opposite Novig side
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
        market=market_key,
        plays=top_plays,
        sgp_suggestion=sgp_suggestion,
    )


# Static frontend (index.html, value.html, etc. under ./frontend)
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
