"""
Detect stay extensions from iCal diff results.

When a guest extends their stay on Airbnb the feed emits:
  - The original booking UID disappears  →  our diff marks it Cancelled
  - A new booking UID appears at same property, same guest, same (or earlier)
    check-in, but a LATER checkout

We cross-reference cancelled bookings against incoming new bookings to
identify this pattern before the manager sees a confusing "cancelled" alert.
"""
from dataclasses import dataclass
from typing import List

from models.booking import Booking
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExtensionEvent:
    old_booking: Booking   # The cancelled booking (shorter stay)
    new_booking: Booking   # The replacement booking (extended stay)

    @property
    def property_name(self) -> str:
        return self.old_booking.property_name

    @property
    def guest_name(self) -> str:
        return self.new_booking.guest_name

    @property
    def old_checkout(self):
        return self.old_booking.checkout

    @property
    def new_checkout(self):
        return self.new_booking.checkout

    @property
    def nights_added(self) -> int:
        return (self.new_checkout - self.old_checkout).days


def _names_match(a: str, b: str) -> bool:
    """
    Fuzzy first-name match. Airbnb sometimes reformats guest names between
    the original booking and the replacement (e.g., "John Smith" → "John S.").
    We only require the first token to agree.
    """
    a_clean = a.lower().strip()
    b_clean = b.lower().strip()
    if a_clean == b_clean:
        return True
    a_first = a_clean.split()[0] if a_clean else ""
    b_first = b_clean.split()[0] if b_clean else ""
    return bool(a_first and b_first and a_first == b_first)


def detect_extensions(
    cancelled: List[Booking],
    new: List[Booking],
) -> List[ExtensionEvent]:
    """
    Return extension events found in a single sync run.

    An extension is detected when:
      - A booking is cancelled (UID gone from feed)
      - A new booking at the same property starts on or before the cancelled
        checkout and ends after the cancelled checkout
      - Guest first names match
    """
    events = []
    for old in cancelled:
        for new_b in new:
            if old.property_id != new_b.property_id:
                continue
            # New stay must start before or on old checkout (contiguous/overlap)
            if new_b.checkin > old.checkout:
                continue
            # New stay must actually be longer
            if new_b.checkout <= old.checkout:
                continue
            if not _names_match(old.guest_name, new_b.guest_name):
                continue
            event = ExtensionEvent(old_booking=old, new_booking=new_b)
            logger.info(
                "Extension detected at '%s': %s was checking out %s, now %s (+%d nights)",
                event.property_name,
                event.guest_name,
                event.old_checkout,
                event.new_checkout,
                event.nights_added,
            )
            events.append(event)

    return events
