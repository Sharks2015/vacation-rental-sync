from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class CleaningTask:
    property_id: str            # Airtable record ID of the Property
    property_name: str
    booking_uid: str            # iCal UID of the triggering checkout booking
    booking_airtable_id: str    # Airtable record ID of the Booking
    cleaning_date: date
    cleaning_start_time: str    # HH:MM
    cleaning_end_time: str      # HH:MM
    cleaner_name: str
    cleaner_phone: str
    cleaning_fee: float
    is_same_day_turnover: bool = False
    next_checkin_date: Optional[date] = None
    next_guest_name: Optional[str] = None
    status: str = "Scheduled"   # Scheduled, In Progress, Completed, Cancelled
    airtable_id: Optional[str] = None
    google_calendar_event_id: Optional[str] = None
    notified: bool = False
