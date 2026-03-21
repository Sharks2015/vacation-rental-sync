from datetime import date, datetime, timedelta
from typing import Union


def to_date(value: Union[date, datetime]) -> date:
    """Normalize icalendar DTSTART/DTEND to a plain date regardless of type."""
    if isinstance(value, datetime):
        return value.date()
    return value


def time_add(start_hhmm: str, hours: float) -> str:
    """Add hours (can be fractional) to a HH:MM string. Returns HH:MM."""
    h, m = map(int, start_hhmm.split(":"))
    total_minutes = h * 60 + m + int(hours * 60)
    total_minutes = total_minutes % (24 * 60)  # wrap at midnight
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def format_date(d: date) -> str:
    """Human-readable date like 'Monday, March 24'."""
    return d.strftime("%A, %B %-d")


def today() -> date:
    return date.today()


def cutoff_date(lookahead_days: int) -> date:
    return today() + timedelta(days=lookahead_days)
