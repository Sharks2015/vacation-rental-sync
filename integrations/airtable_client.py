"""
All Airtable I/O for the vacation rental sync system.

Uses pyairtable which handles pagination and rate limiting automatically.
"""
import time
from datetime import datetime, timezone
from typing import List, Optional

from pyairtable import Api

from config import settings
from models.booking import Booking
from models.cleaning_task import CleaningTask
from models.property import Property
from utils.date_helpers import normalize_time
from utils.logger import get_logger

logger = get_logger(__name__)

# Airtable allows 5 requests/sec. We stay safely under with a small sleep.
_WRITE_DELAY = 0.25


def _get_api() -> Api:
    return Api(settings.AIRTABLE_API_KEY)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def get_all_properties() -> List[Property]:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_PROPERTIES_TABLE)
    records = table.all()
    props = []
    for r in records:
        f = r["fields"]
        # Skip empty records (e.g. created by Make.com test runs)
        if not f:
            continue
        # Active field may be a checkbox (True/False) or text ("Checked")
        active_val = f.get("Active", f.get("Active ", True))
        if isinstance(active_val, str):
            active_val = active_val.strip().lower() in ("checked", "true", "yes", "1")
        if active_val is False:
            continue
        try:
            # Handle slight field name variations
            ical_url = f.get("iCal URL") or f.get("ical URL") or f.get("Ical URL", "")
            cleaning_fee = float(f.get("Cleaning Fee") or f.get("CleaningFee") or 0)
            lodgify_id = f.get("Lodgify Property ID", "")
            props.append(
                Property(
                    airtable_id=r["id"],
                    name=f["Name"],
                    address=f.get("Address", ""),
                    ical_url=ical_url,
                    lodgify_property_id=str(lodgify_id) if lodgify_id else "",
                    secondary_ical_url=f.get("Secondary iCal URL", ""),
                    cleaner_name=f.get("Cleaner Name", ""),
                    cleaner_phone=f.get("Cleaner Phone", ""),
                    cleaning_fee=cleaning_fee,
                    turnover_time_hours=float(f.get("Turnover Time Hours", 3)),
                    google_calendar_id=f.get("Google Calendar ID", ""),
                    active=True,
                    default_checkout_time=f.get("Default Checkout Time", "11:00"),
                    default_checkin_time=f.get("Default Checkin Time", "16:00"),
                )
            )
        except KeyError as e:
            logger.error("Property record %s missing required field: %s", r["id"], e)
    logger.info("Loaded %d active properties from Airtable", len(props))
    return props


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------

def _booking_to_fields(b: Booking) -> dict:
    return {
        "Booking UID": b.uid,
        "Property": [b.property_id],
        "Guest Name": b.guest_name,
        "Check-in Date": b.checkin.isoformat(),
        "Check-out Date": b.checkout.isoformat(),
        "Status": b.status,
        "Raw iCal Summary": b.raw_summary,
    }


def _fields_to_booking(r: dict) -> Booking:
    from datetime import date
    f = r["fields"]
    return Booking(
        uid=f["Booking UID"],
        property_id=f["Property"][0] if f.get("Property") else "",
        property_name=f.get("Property Name (from Property)", [""])[0] if f.get("Property Name (from Property)") else "",
        guest_name=f.get("Guest Name", ""),
        checkin=date.fromisoformat(f["Check-in Date"]),
        checkout=date.fromisoformat(f["Check-out Date"]),
        status=f.get("Status", "Confirmed"),
        raw_summary=f.get("Raw iCal Summary", ""),
        airtable_id=r["id"],
        last_synced_at=f.get("Last Synced At"),
    )


def get_bookings_for_property(property_airtable_id: str) -> List[Booking]:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_BOOKINGS_TABLE)
    # Airtable FIND/ARRAYJOIN doesn't work on linked record fields (returns display
    # name, not record ID). Filter client-side instead.
    records = table.all()
    return [
        _fields_to_booking(r) for r in records
        if property_airtable_id in (r["fields"].get("Property") or [])
    ]


def upsert_booking(booking: Booking) -> Booking:
    """Create or update a booking record. Returns the booking with airtable_id set."""
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_BOOKINGS_TABLE)
    fields = _booking_to_fields(booking)
    time.sleep(_WRITE_DELAY)

    if booking.airtable_id:
        record = table.update(booking.airtable_id, fields)
    else:
        record = table.create(fields)

    booking.airtable_id = record["id"]
    return booking


# ---------------------------------------------------------------------------
# Cleaning Tasks
# ---------------------------------------------------------------------------

def _task_to_fields(t: CleaningTask) -> dict:
    fields = {
        "Property": [t.property_id],
        "Booking": [t.booking_airtable_id] if t.booking_airtable_id else [],
        "Booking UID": t.booking_uid,
        "Cleaning Date": t.cleaning_date.isoformat(),
        "Cleaning Start Time": normalize_time(t.cleaning_start_time),
        "Cleaning End Time": normalize_time(t.cleaning_end_time),
        "Cleaner": t.cleaner_name,
        "Cleaner Phone": t.cleaner_phone,
        "Cleaning Fee": t.cleaning_fee,
        "Is Same Day Turnover?": t.is_same_day_turnover,
        "Status": t.status,
        "Notified": t.notified,
    }
    if t.next_checkin_date:
        fields["Next Check In Date"] = t.next_checkin_date.isoformat()
    if t.next_guest_name:
        fields["Next Guest Name"] = t.next_guest_name
    if t.google_calendar_event_id:
        fields["Google Calendar Event ID"] = t.google_calendar_event_id
    return fields


def _fields_to_task(r: dict) -> CleaningTask:
    from datetime import date
    f = r["fields"]
    return CleaningTask(
        airtable_id=r["id"],
        property_id=f["Property"][0] if f.get("Property") else "",
        property_name=f.get("Property Name (from Property)", [""])[0] if f.get("Property Name (from Property)") else "",
        booking_uid=f.get("Booking UID", ""),
        booking_airtable_id=f["Booking"][0] if f.get("Booking") else "",
        cleaning_date=date.fromisoformat(f["Cleaning Date"]),
        cleaning_start_time=f.get("Cleaning Start Time", "11:00"),
        cleaning_end_time=f.get("Cleaning End Time", "14:00"),
        cleaner_name=f.get("Cleaner", ""),
        cleaner_phone=f.get("Cleaner Phone", ""),
        cleaning_fee=float(f.get("Cleaning Fee", 0)),
        is_same_day_turnover=f.get("Is Same-Day Turnover", False),
        next_checkin_date=date.fromisoformat(f["Next Check-in Date"]) if f.get("Next Check-in Date") else None,
        next_guest_name=f.get("Next Guest Name"),
        status=f.get("Status", "Scheduled"),
        google_calendar_event_id=f.get("Google Calendar Event ID"),
        notified=f.get("Notified", False),
    )


def get_task_by_booking_uid(booking_uid: str) -> Optional[CleaningTask]:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_TASKS_TABLE)
    # Escape single quotes in uid
    safe_uid = booking_uid.replace("'", "\\'")
    formula = f"{{Booking UID}} = '{safe_uid}'"
    records = table.all(formula=formula)
    if not records:
        return None
    return _fields_to_task(records[0])


def get_tasks_for_property(property_airtable_id: str) -> List[CleaningTask]:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_TASKS_TABLE)
    formula = f"FIND('{property_airtable_id}', ARRAYJOIN({{Property}}))"
    records = table.all(formula=formula)
    return [_fields_to_task(r) for r in records]


def create_task(task: CleaningTask) -> CleaningTask:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_TASKS_TABLE)
    time.sleep(_WRITE_DELAY)
    record = table.create(_task_to_fields(task))
    task.airtable_id = record["id"]
    return task


def update_task(airtable_id: str, task: CleaningTask) -> CleaningTask:
    api = _get_api()
    table = api.table(settings.AIRTABLE_BASE_ID, settings.AIRTABLE_TASKS_TABLE)
    time.sleep(_WRITE_DELAY)
    table.update(airtable_id, _task_to_fields(task))
    return task
