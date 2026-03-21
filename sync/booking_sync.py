from dataclasses import dataclass
from typing import List

from models.booking import Booking
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BookingDiff:
    new: List[Booking]
    modified: List[Booking]
    cancelled: List[Booking]   # UIDs present in Airtable but gone from iCal feed
    unchanged: List[Booking]


def diff(fetched: List[Booking], existing: List[Booking]) -> BookingDiff:
    """
    Compare the live iCal feed against what's stored in Airtable.

    A booking is "cancelled" if its UID has disappeared from the feed.
    A booking is "modified" if checkin, checkout, or guest name changed.
    """
    fetched_by_uid = {b.uid: b for b in fetched}
    existing_by_uid = {b.uid: b for b in existing}

    new_uids = fetched_by_uid.keys() - existing_by_uid.keys()
    removed_uids = existing_by_uid.keys() - fetched_by_uid.keys()
    shared_uids = fetched_by_uid.keys() & existing_by_uid.keys()

    new_bookings = [fetched_by_uid[u] for u in new_uids]

    cancelled_bookings = []
    for u in removed_uids:
        b = existing_by_uid[u]
        if b.status != "Cancelled":  # avoid re-processing already-cancelled
            b_copy = Booking(**b.__dict__)
            b_copy.status = "Cancelled"
            cancelled_bookings.append(b_copy)

    modified_bookings = []
    unchanged_bookings = []
    for u in shared_uids:
        fetched_b = fetched_by_uid[u]
        existing_b = existing_by_uid[u]
        # Carry the Airtable record ID forward so we can update it
        fetched_b.airtable_id = existing_b.airtable_id
        if (
            fetched_b.checkin != existing_b.checkin
            or fetched_b.checkout != existing_b.checkout
            or fetched_b.guest_name != existing_b.guest_name
            or fetched_b.status != existing_b.status
        ):
            modified_bookings.append(fetched_b)
        else:
            unchanged_bookings.append(fetched_b)

    logger.info(
        "Diff result — new: %d, modified: %d, cancelled: %d, unchanged: %d",
        len(new_bookings),
        len(modified_bookings),
        len(cancelled_bookings),
        len(unchanged_bookings),
    )
    return BookingDiff(
        new=new_bookings,
        modified=modified_bookings,
        cancelled=cancelled_bookings,
        unchanged=unchanged_bookings,
    )
