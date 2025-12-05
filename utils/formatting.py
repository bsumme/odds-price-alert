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
    If parsing fails, returns the original string or a fallback message.
    """
    if not iso_str:
        return "—"
    
    try:
        from datetime import datetime
        # Handle both ISO format with Z and +00:00
        cleaned_str = iso_str.strip().replace("Z", "+00:00")
        if not cleaned_str:
            return "—"
        
        dt_utc = datetime.fromisoformat(cleaned_str)
        dt_et = dt_utc.astimezone(ZoneInfo("America/New_York"))
        formatted = dt_et.strftime("%a, %b %d, %I:%M %p ET")
        
        # Handle leading zero in day (e.g., " 01" -> " 1")
        if formatted[8:10] == " 0" and formatted[10].isdigit():
            formatted = formatted[:8] + " " + formatted[10:]
        
        return formatted
    except Exception as e:
        # Return original string if it looks like ISO format, otherwise return dash
        if iso_str and (iso_str.startswith("20") or "T" in iso_str):
            return iso_str
        return "—"








