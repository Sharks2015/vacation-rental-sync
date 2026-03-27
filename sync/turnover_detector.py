from typing import List, Callable, Optional

from models.booking import Booking
from models.cleaning_task import CleaningTask
from utils.logger import get_logger

logger = get_logger(__name__)


def detect_and_flag(
    all_bookings: List[Booking],
    get_task_by_uid: Callable[[str], Optional[CleaningTask]],
    update_task: Callable[[str, CleaningTask], CleaningTask],
) -> List[CleaningTask]:
    """
    Find same-day turnovers (checkout of booking A == checkin of booking B)
    and flag the corresponding cleaning tasks.

    Must be called AFTER all booking cancellations have been processed so that
    cancelled bookings no longer appear in all_bookings.
    """
    confirmed = [b for b in all_bookings if b.is_real_reservation()]
    confirmed.sort(key=lambda b: b.checkin)

    flagged: List[CleaningTask] = []

    for i, booking in enumerate(confirmed):
        if i + 1 >= len(confirmed):
            break
        next_booking = confirmed[i + 1]

        if booking.checkout == next_booking.checkin:
            task = get_task_by_uid(booking.uid)
            if not task:
                logger.warning(
                    "Same-day turnover detected but no task found for uid=%s", booking.uid
                )
                continue

            was_already_flagged = task.is_same_day_turnover

            task.is_same_day_turnover = True
            task.next_checkin_date = next_booking.checkin
            task.next_guest_name = next_booking.guest_name

            if not was_already_flagged:
                task.notified = False  # Trigger a priority SMS

            updated = update_task(task.airtable_id, task)
            flagged.append(updated)

            logger.info(
                "Same-day turnover at '%s' on %s — %s checks out, %s checks in",
                task.property_name,
                booking.checkout,
                booking.guest_name,
                next_booking.guest_name,
            )

    # Clear stale flags: if a booking is no longer same-day, unflag it
    for booking in confirmed:
        task = get_task_by_uid(booking.uid)
        if task and task.is_same_day_turnover:
            if task not in flagged:
                task.is_same_day_turnover = False
                task.next_checkin_date = None
                task.next_guest_name = None
                update_task(task.airtable_id, task)
                logger.info("Cleared stale same-day turnover flag for uid=%s", booking.uid)

    return flagged
