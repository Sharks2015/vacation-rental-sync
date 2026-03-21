import re
import requests
from datetime import date
from typing import List

from icalendar import Calendar

from models.booking import Booking
from models.property import Property
from utils.date_helpers import to_date
from utils.logger import get_logger

logger = get_logger(__name__)

# Airbnb uses this summary text for owner blocks / unavailable periods
_BLOCK_PATTERNS = [
    r"Not available",
    r"Airbnb \(Not available\)",
    r"Owner Block",
    r"Blocked",
]
_BLOCK_RE = re.compile("|".join(_BLOCK_PATTERNS), re.IGNORECASE)

# Airbnb reservation summaries look like:
#   "Reserved" or "Reservation - John Smith" or "John Smith"
_GUEST_RE = re.compile(r"(?:Reservation\s*[-–]\s*|Reserved\s*[-–]\s*)?(.+)", re.IGNORECASE)


def _extract_guest_name(summary: str) -> str:
    m = _GUEST_RE.match(summary.strip())
    if m:
        name = m.group(1).strip()
        # Strip trailing parenthetical noise like "(Airbnb)"
        name = re.sub(r"\s*\(.*\)\s*$", "", name)
        return name or "Unknown Guest"
    return "Unknown Guest"


def fetch_and_parse(prop: Property) -> List[Booking]:
    """Fetch an iCal URL and return a list of Booking objects for that property."""
    try:
        resp = requests.get(prop.ical_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to fetch iCal for '%s': %s", prop.name, e)
        return []

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as e:
        logger.error("Failed to parse iCal for '%s': %s", prop.name, e)
        return []

    bookings: List[Booking] = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        uid = str(component.get("UID", ""))
        summary = str(component.get("SUMMARY", ""))
        dtstart = component.get("DTSTART")
        dtend = component.get("DTEND")

        if not uid or not dtstart or not dtend:
            logger.warning("Skipping malformed VEVENT in '%s': uid=%s", prop.name, uid)
            continue

        checkin: date = to_date(dtstart.dt)
        checkout: date = to_date(dtend.dt)

        if _BLOCK_RE.search(summary):
            status = "Blocked"
            guest_name = "N/A"
        else:
            status = "Confirmed"
            guest_name = _extract_guest_name(summary)

        bookings.append(
            Booking(
                uid=uid,
                property_id=prop.airtable_id,
                property_name=prop.name,
                guest_name=guest_name,
                checkin=checkin,
                checkout=checkout,
                status=status,
                raw_summary=summary,
            )
        )

    logger.info("Fetched %d events for '%s'", len(bookings), prop.name)
    return bookings
