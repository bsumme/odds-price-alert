"""Odds conversion and calculation utilities."""

MAX_VALID_AMERICAN_ODDS = 10000


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds > 0:
        return 1.0 + odds / 100.0
    else:
        return 1.0 + 100.0 / abs(odds)


def decimal_to_american(decimal: float) -> int:
    """Convert decimal odds to American odds."""
    if decimal >= 2.0:
        return int((decimal - 1.0) * 100)
    else:
        return int(-100.0 / (decimal - 1.0))


def american_to_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
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


def is_price_or_better(current: int, target: int) -> bool:
    """
    Implements "or better" logic for American odds.

    - If target is positive (e.g. +120), we want current >= target
      (+130 is better than +120).

    - If target is negative (e.g. -290), we want current >= target as well,
      because -200 >= -290 (and -200 is "better" than -290).
    """
    return current >= target


def points_match(
    book_point: float | None,
    novig_point: float | None,
    allow_half_point_flex: bool,
) -> bool:
    """Determine if two points should be treated as matching.

    For most markets we require an exact match (including both being None).
    For spreads/totals, The Odds API occasionally publishes a 0.5-point
    difference between Novig and the target book; when allow_half_point_flex
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

    vig_percentages = {
        "fliff": 0.30,
        "draftkings": 0.20,
        "fanduel": 0.20,
    }

    vig_pct = vig_percentages.get(bookmaker_key.lower(), 0.0)
    if vig_pct == 0.0:
        return odds

    dec_odds = american_to_decimal(odds)
    buffer = 0.01
    adjusted_dec = dec_odds * (1.0 - vig_pct - buffer)
    adjusted_american = decimal_to_american(adjusted_dec)

    if odds > 0:
        if adjusted_american <= 0:
            adjusted_american = max(100, odds - 50)
        if adjusted_american >= odds:
            adjusted_american = max(100, odds - 50)

    common_odds = [
        -10000, -5000, -2500, -2000, -1500, -1200, -1000, -900, -800, -700, -600, -550,
        -500, -475, -450, -425, -400, -375, -350, -325, -300, -275, -250, -225, -200,
        -190, -180, -170, -160, -150, -140, -130, -120, -115, -110, -105, -102,
        100, 102, 105, 110, 115, 120, 130, 140, 150, 160, 170, 180, 190,
        200, 225, 250, 275, 300, 325, 350, 375, 400, 425, 450, 475, 500,
        550, 600, 700, 800, 900, 1000, 1200, 1500, 2000, 2500, 5000, 10000
    ]

    if odds > 0:
        positive_common_odds = [x for x in common_odds if x > 0]
        worse_options = [x for x in positive_common_odds if x < adjusted_american and x < odds]
        if worse_options:
            closest = max(worse_options)
        else:
            closest = max(100, int(adjusted_american))
            if closest >= odds:
                worse_values = [x for x in positive_common_odds if x < odds]
                if worse_values:
                    closest = max(worse_values)
                else:
                    closest = max(100, odds - 50)
        return closest
    else:
        worse_options = [x for x in common_odds if x < adjusted_american and x < odds]
        if worse_options:
            closest = max(worse_options)
        else:
            closest = int(adjusted_american)
            if closest >= odds:
                worse_values = [x for x in common_odds if x < odds]
                if worse_values:
                    closest = max(worse_values)
                else:
                    closest = odds - 10
        return closest



