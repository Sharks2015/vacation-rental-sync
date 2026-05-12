"""
Vacation Rental Cleaning Automation — Main Sync Script

Run on a cron schedule (every 2 hours recommended):
    0 */2 * * * /path/to/venv/bin/python /path/to/vacation-rental-sync/main.py

This script is fully idempotent. Running it multiple times produces no
duplicate records or duplicate SMS messages.
"""
import sys
import urllib.request
import json
from datetime import timedelta

from config import settings
from integrations import airtable_client as airtable
from integrations import google_calendar
from integrations import lodgify_client
from integrations import twilio_sms
from sync import ical_fetcher
from sync.booking_sync import diff
from sync.cleaning_scheduler import (
    apply_cancelled_booking,
    apply_modified_booking,
    apply_new_booking,
)
from sync.extension_detector import detect_extensions
from sync.turnover_detector import detect_and_flag
from utils.date_helpers import format_date, today
from utils.logger import get_logger

logger = get_logger("main")


def _notify_extension(event) -> None:
    """Alert owner via GHL webhook when a stay extension is detected."""
    nights = event.nights_added
    body = (
        f"STAY EXTENDED — {event.property_name}: "
        f"{event.guest_name} was checking out {format_date(event.old_checkout)}, "
        f"now checks out {format_date(event.new_checkout)} "
        f"(+{nights} night{'s' if nights != 1 else ''}). "
        f"Cleaning has been rescheduled."
    )
    if settings.EXTENSION_WEBHOOK_URL:
        try:
            payload = json.dumps({
                "owner_phone": settings.OWNER_PHONE,
                "owner_email": settings.OWNER_EMAIL,
                "sms_body": body,
            }).encode()
            req = urllib.request.Request(
                settings.EXTENSION_WEBHOOK_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(
                    "Extension alert sent via GHL — '%s': %s → %s",
                    event.property_name, event.old_checkout, event.new_checkout,
                )
        except Exception as e:
            logger.error("Failed to send extension alert via GHL: %s", e)
    else:
        sent = twilio_sms.notify_extension(event)
        if sent:
            logger.info(
                "Extension SMS sent via Twilio — '%s': %s → %s",
                event.property_name, event.old_checkout, event.new_checkout,
            )


def _notify_new_clean(task, booking) -> None:
    """Email owner via GHL when a new cleaning task is created."""
    if not settings.NEW_CLEAN_WEBHOOK_URL:
        return
    subject = f"New Clean Scheduled — {task.property_name}"
    body = (
        f"Property: {task.property_name}\n"
        f"Guest: {booking.guest_name}\n"
        f"Cleaning Date: {format_date(task.cleaning_date)}\n"
        f"Time: {task.cleaning_start_time} – {task.cleaning_end_time}\n"
        f"Cleaner: {task.cleaner_name or 'TBD'}"
    )
    try:
        payload = json.dumps({
            "owner_phone": settings.OWNER_PHONE,
            "owner_email": settings.OWNER_EMAIL,
            "email_subject": subject,
            "email_body": body,
        }).encode()
        req = urllib.request.Request(
            settings.NEW_CLEAN_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            logger.info("New clean email sent — '%s' on %s", task.property_name, task.cleaning_date)
    except Exception as e:
        logger.error("Failed to send new clean email via GHL: %s", e)


def sync_property(prop):
    logger.info("=== Syncing property: %s ===", prop.name)

    # Step 1: Fetch live bookings from Lodgify API or iCal
    if prop.lodgify_property_id and settings.LODGIFY_API_KEY:
        fetched_bookings = lodgify_client.get_bookings_for_property(
            settings.LODGIFY_API_KEY,
            int(prop.lodgify_property_id),
            prop.airtable_id,
            prop.name,
        )
    else:
        fetched_bookings = ical_fetcher.fetch_and_parse(prop)
    if not fetched_bookings:
        logger.warning("No bookings fetched for '%s' — skipping", prop.name)
        return

    # Filter to relevant window: LOOKBACK_DAYS ago through LOOKAHEAD_DAYS ahead
    window_start = today() - timedelta(days=settings.SYNC_LOOKBACK_DAYS)
    window_end = today() + timedelta(days=settings.SYNC_LOOKAHEAD_DAYS)
    fetched_bookings = [
        b for b in fetched_bookings
        if window_start <= b.checkout <= window_end
    ]

    # Step 2: Get current Airtable state
    existing_bookings = airtable.get_bookings_for_property(prop.airtable_id)

    # Step 3: Diff
    result = diff(fetched_bookings, existing_bookings)

    # Step 3b: Detect stay extensions before writing to Airtable.
    # An extension looks like: old UID cancelled + new UID at same property,
    # same guest, same/earlier check-in, later checkout — all in one sync run.
    extensions = detect_extensions(result.cancelled, result.new)
    extension_old_uids = {e.old_booking.uid for e in extensions}

    # Step 4: Upsert bookings into Airtable
    for booking in result.new + result.modified:
        airtable.upsert_booking(booking)

    for booking in result.cancelled:
        airtable.upsert_booking(booking)  # Updates status to Cancelled

    # Step 5: Schedule / update / cancel cleaning tasks
    new_tasks = []
    for booking in result.new:
        task = apply_new_booking(
            booking, prop,
            airtable.get_task_by_booking_uid,
            airtable.create_task,
        )
        if task:
            new_tasks.append((task, booking))

    modified_tasks = []
    for booking in result.modified:
        task = apply_modified_booking(
            booking, prop,
            airtable.get_task_by_booking_uid,
            airtable.update_task,
        )
        if task:
            modified_tasks.append((task, booking))

    cancelled_tasks = []
    for booking in result.cancelled:
        task = apply_cancelled_booking(
            booking,
            airtable.get_task_by_booking_uid,
            airtable.update_task,
        )
        if task:
            cancelled_tasks.append((task, booking))

    # Step 5b: Re-label extended tasks in Airtable so they show "Extended"
    # instead of "Cancelled" — makes it instantly clear in today's task view.
    # Requires "Extended" to be a Select option in the Cleaning Tasks Status field.
    for task, booking in cancelled_tasks:
        if booking.uid in extension_old_uids and task.airtable_id:
            try:
                task.status = "Extended"
                airtable.update_task(task.airtable_id, task)
                logger.info("Marked task as Extended for booking %s at '%s'", booking.uid, prop.name)
            except Exception as e:
                logger.error("Could not set Extended status (add 'Extended' option to Airtable Status field): %s", e)

    # Step 6: Re-run turnover detection on the full confirmed set
    all_current_bookings = [
        b for b in fetched_bookings if b.status != "Cancelled"
    ] + [b for b in result.unchanged]

    same_day_tasks = detect_and_flag(
        all_current_bookings,
        airtable.get_task_by_booking_uid,
        airtable.update_task,
    )
    same_day_uids = {t.booking_uid for t in same_day_tasks}

    # Step 7: Sync Google Calendar for all touched tasks
    all_touched_tasks = (
        [t for t, _ in new_tasks]
        + [t for t, _ in modified_tasks]
        + [t for t, _ in cancelled_tasks]
        + same_day_tasks
    )
    for task in all_touched_tasks:
        google_calendar.sync_task(task, prop, airtable.update_task)

    # Step 8: Send SMS notifications
    for task, booking in new_tasks:
        if task.booking_uid in same_day_uids:
            twilio_sms.notify_same_day_turnover(task, airtable.update_task)
        else:
            twilio_sms.notify_new_booking(task, booking, airtable.update_task)

    for task, booking in modified_tasks:
        twilio_sms.notify_modified_booking(task, booking, airtable.update_task)

    for task, booking in cancelled_tasks:
        twilio_sms.notify_cancelled_booking(task, booking, airtable.update_task)

    # Notify any newly detected same-day turnovers not already covered above
    for task in same_day_tasks:
        if not any(task.booking_uid == t.booking_uid for t, _ in new_tasks):
            twilio_sms.notify_same_day_turnover(task, airtable.update_task)

    # Step 9: Alert owner on stay extensions
    for event in extensions:
        _notify_extension(event)

    # Step 10: Email owner for each new cleaning task
    for task, booking in new_tasks:
        _notify_new_clean(task, booking)

    logger.info("Finished syncing '%s'", prop.name)


def main():
    logger.info("Starting vacation rental sync")
    lodgify_client.reset_cache()  # Fresh fetch each sync run
    properties = airtable.get_all_properties()

    if not properties:
        logger.warning("No active properties found — nothing to sync")
        sys.exit(0)

    errors = []
    for prop in properties:
        try:
            sync_property(prop)
        except Exception as e:
            logger.error("Unhandled error syncing '%s': %s", prop.name, e, exc_info=True)
            errors.append(prop.name)

    if errors:
        logger.error("Sync completed with errors in: %s", ", ".join(errors))
        sys.exit(1)
    else:
        logger.info("Sync completed successfully")


if __name__ == "__main__":
    main()
