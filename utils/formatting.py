"""Formatting utilities for odds tracking application."""

from zoneinfo import ZoneInfo

BOOK_LABELS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "novig": "Novig",
    "fliff": "Fliff",
}


def pretty_book_label(book_key: str) -> str:
    """Convert bookmaker key to display label."""
    return BOOK_LABELS.get(book_key, book_key)


def format_start_time_est(iso_str: str) -> str:
    """Convert an ISO UTC time string into an easy-to-read EST label.

    Example output: "Thu, Nov 20, 3:30 PM ET".
    If parsing fails, returns the original string.
    """
    try:
        from datetime import datetime
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        formatted = dt_et.strftime("%a, %b %d, %I:%M %p ET")
        if formatted[8:10] == " 0" and formatted[10].isdigit():
            formatted = formatted[:8] + " " + formatted[10:]
        return formatted
    except Exception:
        return iso_str

