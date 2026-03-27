"""
Vacation Rental Cleaning Automation — Main Sync Script

Run on a cron schedule (every 2 hours recommended):
    0 */2 * * * /path/to/venv/bin/python /path/to/vacation-rental-sync/main.py

This script is fully idempotent. Running it multiple times produces no
duplicate records or duplicate SMS messages.
"""
import sys
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
from sync.turnover_detector import detect_and_flag
from utils.date_helpers import today
from utils.logger import get_logger

logger = get_logger("main")


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
