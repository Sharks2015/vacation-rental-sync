from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Booking:
    uid: str                        # iCal VEVENT UID — stable dedup key
    property_id: str                # Airtable record ID of the Property
    property_name: str
    guest_name: str
    checkin: date
    checkout: date
    status: str                     # "Confirmed", "Cancelled", "Blocked"
    raw_summary: str = ""
    airtable_id: Optional[str] = None   # Populated after first write to Airtable
    last_synced_at: Optional[str] = None

    @property
    def nights(self) -> int:
        return (self.checkout - self.checkin).days

    def is_real_reservation(self) -> bool:
        """Airbnb also emits 'Not available' block events — ignore those for tasks."""
        return self.status == "Confirmed"
