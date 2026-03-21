from datetime import date
from typing import List, Optional

from models.booking import Booking
from models.cleaning_task import CleaningTask
from models.property import Property
from utils.date_helpers import time_add, today
from utils.logger import get_logger

logger = get_logger(__name__)


def build_task_for_booking(booking: Booking, prop: Property) -> CleaningTask:
    start = prop.default_checkout_time
    end = time_add(start, prop.turnover_time_hours)
    return CleaningTask(
        property_id=prop.airtable_id,
        property_name=prop.name,
        booking_uid=booking.uid,
        booking_airtable_id=booking.airtable_id or "",
        cleaning_date=booking.checkout,
        cleaning_start_time=start,
        cleaning_end_time=end,
        cleaner_name=prop.cleaner_name,
        cleaner_phone=prop.cleaner_phone,
        cleaning_fee=prop.cleaning_fee,
    )


def should_create_task(booking: Booking, prop: Property) -> bool:
    """Only create tasks for real upcoming reservations."""
    if not booking.is_real_reservation():
        return False
    # Don't backfill historical checkouts (beyond lookback window handled in main)
    if booking.checkout < today():
        return False
    return True


def apply_new_booking(
    booking: Booking,
    prop: Property,
    get_task_by_uid,
    create_task,
) -> Optional[CleaningTask]:
    """Create a cleaning task for a new booking if one doesn't already exist."""
    if not should_create_task(booking, prop):
        return None
    existing = get_task_by_uid(booking.uid)
    if existing:
        logger.warning("Task already exists for uid=%s — skipping create", booking.uid)
        return existing
    task = build_task_for_booking(booking, prop)
    created = create_task(task)
    logger.info("Created cleaning task for '%s' checkout on %s", prop.name, booking.checkout)
    return created


def apply_modified_booking(
    booking: Booking,
    prop: Property,
    get_task_by_uid,
    update_task,
) -> Optional[CleaningTask]:
    """Update an existing task when a booking's dates change."""
    existing = get_task_by_uid(booking.uid)
    if not existing:
        # No task yet — create one fresh
        return apply_new_booking(booking, prop, get_task_by_uid, lambda t: update_task(None, t))

    if existing.status == "Completed":
        logger.info("Task for uid=%s is Completed — not modifying", booking.uid)
        return existing

    start = prop.default_checkout_time
    end = time_add(start, prop.turnover_time_hours)
    existing.cleaning_date = booking.checkout
    existing.cleaning_start_time = start
    existing.cleaning_end_time = end
    existing.booking_airtable_id = booking.airtable_id or existing.booking_airtable_id
    # Re-queue for notification on date change
    existing.notified = False

    updated = update_task(existing.airtable_id, existing)
    logger.info("Updated cleaning task for '%s' checkout on %s", prop.name, booking.checkout)
    return updated


def apply_cancelled_booking(
    booking: Booking,
    get_task_by_uid,
    update_task,
) -> Optional[CleaningTask]:
    """Cancel the cleaning task when a booking is cancelled."""
    existing = get_task_by_uid(booking.uid)
    if not existing:
        return None
    if existing.status == "Completed":
        logger.info("Task for uid=%s is Completed — not cancelling", booking.uid)
        return existing

    existing.status = "Cancelled"
    existing.notified = False  # Re-notify so cleaner hears about cancellation
    updated = update_task(existing.airtable_id, existing)
    logger.info("Cancelled cleaning task for uid=%s", booking.uid)
    return updated
