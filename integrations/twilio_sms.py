"""
SMS notifications via Twilio.

All messages are gated by task.notified to prevent duplicate sends.
After sending, call airtable_update_fn to persist notified=True.
"""
from twilio.rest import Client

from config import settings
from models.booking import Booking
from models.cleaning_task import CleaningTask
from utils.date_helpers import format_date
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_client() -> Client:
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def _send(to: str, body: str) -> bool:
    if not to:
        logger.warning("No phone number to send SMS to — skipping")
        return False
    try:
        client = _get_client()
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_FROM_NUMBER,
            to=to,
        )
        logger.info("SMS sent to %s (SID: %s)", to, message.sid)
        return True
    except Exception as e:
        logger.error("Failed to send SMS to %s: %s", to, e)
        return False


def notify_new_booking(
    task: CleaningTask,
    booking: Booking,
    airtable_update_fn,
) -> None:
    if task.notified:
        return
    body = (
        f"New booking at {task.property_name}: "
        f"{booking.guest_name} checks out {format_date(task.cleaning_date)}. "
        f"Cleaning scheduled {task.cleaning_start_time}–{task.cleaning_end_time}."
    )
    if _send(task.cleaner_phone, body):
        task.notified = True
        airtable_update_fn(task.airtable_id, task)


def notify_modified_booking(
    task: CleaningTask,
    booking: Booking,
    airtable_update_fn,
) -> None:
    if task.notified:
        return
    body = (
        f"UPDATED booking at {task.property_name}: "
        f"{booking.guest_name} now checks out {format_date(task.cleaning_date)}. "
        f"Cleaning moved to {task.cleaning_start_time}–{task.cleaning_end_time}."
    )
    if _send(task.cleaner_phone, body):
        task.notified = True
        airtable_update_fn(task.airtable_id, task)


def notify_cancelled_booking(
    task: CleaningTask,
    booking: Booking,
    airtable_update_fn,
) -> None:
    if task.notified:
        return
    body = (
        f"CANCELLED: {booking.guest_name} booking at {task.property_name} "
        f"on {format_date(task.cleaning_date)} was cancelled. Cleaning task removed."
    )
    if _send(task.cleaner_phone, body):
        task.notified = True
        airtable_update_fn(task.airtable_id, task)


def notify_same_day_turnover(
    task: CleaningTask,
    airtable_update_fn,
) -> None:
    if task.notified:
        return
    body = (
        f"SAME-DAY TURNOVER at {task.property_name} on {format_date(task.cleaning_date)}. "
        f"Must finish by {task.cleaning_end_time}. "
        f"Next guest: {task.next_guest_name or 'Unknown'} arriving {task.next_checkin_date}."
    )
    if _send(task.cleaner_phone, body):
        task.notified = True
        airtable_update_fn(task.airtable_id, task)
