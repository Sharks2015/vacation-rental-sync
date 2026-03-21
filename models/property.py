from dataclasses import dataclass
from typing import Optional


@dataclass
class Property:
    airtable_id: str           # Airtable record ID (recXXXXXX)
    name: str
    address: str
    ical_url: str
    cleaner_name: str
    cleaner_phone: str         # E.164 format: +15550001234
    cleaning_fee: float
    turnover_time_hours: float
    google_calendar_id: str
    active: bool = True
    default_checkout_time: str = "11:00"  # HH:MM, local time
    default_checkin_time: str = "16:00"   # HH:MM, used for same-day turnover deadline
