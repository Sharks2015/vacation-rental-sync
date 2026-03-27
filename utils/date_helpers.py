from datetime import date, datetime, timedelta
from typing import Union


def to_date(value: Union[date, datetime]) -> date:
    """Normalize icalendar DTSTART/DTEND to a plain date regardless of type."""
    if isinstance(value, datetime):
        return value.date()
    return value


def normalize_time(t: str) -> str:
    """Convert any time format (11am, 11:00, 4pm, 16:00) to 12-hour format (10:00 AM, 4:00 PM)."""
    t = t.strip().lower().replace(" ", "")
    # Already in 12-hour format like "10:00 am" or "4:00 pm"
    if "am" in t or "pm" in t:
        suffix = "AM" if "am" in t else "PM"
        time_part = t.replace("am", "").replace("pm", "")
        if ":" in time_part:
            h, m = time_part.split(":")
        else:
            h, m = time_part, "00"
        return f"{int(h)}:{m.zfill(2)} {suffix}"
    # 24-hour format like "16:00" or "10:00"
    if ":" in t:
        h, m = map(int, t.split(":"))
    else:
        h, m = int(t), 0
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def _to_minutes(t: str) -> int:
    """Convert a time string to total minutes since midnight (internal use)."""
    t = t.strip().lower().replace(" ", "")
    suffix = ""
    if "am" in t:
        suffix = "am"
        t = t.replace("am", "")
    elif "pm" in t:
        suffix = "pm"
        t = t.replace("pm", "")
    if ":" in t:
        h, m = map(int, t.split(":"))
    else:
        h, m = int(t), 0
    if suffix == "pm" and h != 12:
        h += 12
    if suffix == "am" and h == 12:
        h = 0
    return h * 60 + m


def time_add(start: str, hours: float) -> str:
    """Add hours to a time string. Returns 12-hour format (e.g. '4:00 PM')."""
    total_minutes = _to_minutes(start) + int(hours * 60)
    total_minutes = total_minutes % (24 * 60)
    h, m = divmod(total_minutes, 60)
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def format_date(d: date) -> str:
    """Human-readable date like 'Monday, March 24'."""
    return d.strftime("%A, %B %-d")


def today() -> date:
    return date.today()


def cutoff_date(lookahead_days: int) -> date:
    return today() + timedelta(days=lookahead_days)
