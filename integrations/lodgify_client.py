"""
Lodgify API integration — fetches properties and bookings.
Used as an alternative to iCal for Lodgify-managed properties.
"""
import requests
from datetime import date, timedelta
from typing import List

from models.booking import Booking
from models.property import Property
from utils.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://api.lodgify.com/v2"
_LOOKFORWARD_DAYS = 90


def _headers(api_key: str) -> dict:
    return {"X-ApiKey": api_key, "Accept": "application/json"}


def get_properties(api_key: str) -> List[dict]:
    """Return raw Lodgify property list."""
    resp = requests.get(f"{_BASE}/properties", headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    return resp.json().get("items", [])


_all_bookings_cache: list = []
_cache_fetched: bool = False


def _fetch_all_bookings(api_key: str) -> list:
    """Fetch all bookings from Lodgify in one call (API doesn't support per-property filtering)."""
    global _all_bookings_cache, _cache_fetched
    if _cache_fetched:
        return _all_bookings_cache

    try:
        resp = requests.get(
            f"{_BASE}/reservations/bookings",
            headers=_headers(api_key),
            params={"size": 500},
            timeout=30,
        )
        resp.raise_for_status()
        _all_bookings_cache = resp.json().get("items", [])
        _cache_fetched = True
        logger.info("Fetched %d total bookings from Lodgify", len(_all_bookings_cache))
    except requests.RequestException as e:
        logger.error("Failed to fetch Lodgify bookings: %s", e)
        _all_bookings_cache = []

    return _all_bookings_cache


def reset_cache():
    """Call this at the start of each sync run to clear the cache."""
    global _cache_fetched
    _cache_fetched = False


def get_bookings_for_property(api_key: str, property_id: int, airtable_property_id: str, property_name: str) -> List[Booking]:
    """Return bookings for a specific Lodgify property, filtered from the full list."""
    today = date.today()
    until = today + timedelta(days=_LOOKFORWARD_DAYS)
    all_items = _fetch_all_bookings(api_key)

    bookings = []
    for item in all_items:
        # Filter by this property's Lodgify ID
        if item.get("property_id") != property_id:
            continue

        arrival = item.get("arrival")
        departure = item.get("departure")
        if not arrival or not departure:
            continue

        # Only include bookings within our window
        checkin = date.fromisoformat(arrival)
        checkout = date.fromisoformat(departure)
        if checkout < today or checkin > until:
            continue

        uid = f"lodgify-{item['id']}"
        guest_name = item.get("guest", {}).get("name", "Unknown Guest")
        status_raw = item.get("status", "")
        status = "Cancelled" if status_raw in ("Canceled", "Declined", "cancelled") else "Confirmed"

        bookings.append(
            Booking(
                uid=uid,
                property_id=airtable_property_id,
                property_name=property_name,
                guest_name=guest_name,
                checkin=checkin,
                checkout=checkout,
                status=status,
                raw_summary=f"Lodgify: {guest_name}",
            )
        )

    logger.info("Filtered %d bookings for '%s' (Lodgify ID: %s)", len(bookings), property_name, property_id)
    return bookings
