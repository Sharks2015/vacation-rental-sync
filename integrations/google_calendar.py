"""
Google Calendar integration using a service account (no browser OAuth needed).

Setup:
1. Create a Google Cloud project and enable the Calendar API.
2. Create a Service Account and download the JSON key file.
3. Set GOOGLE_SERVICE_ACCOUNT_FILE in .env pointing to that JSON file.
4. In Google Calendar, share each property's calendar with the service account email
   (give it "Make changes to events" permission).
"""
import time
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import settings
from models.cleaning_task import CleaningTask
from models.property import Property
from utils.logger import get_logger

logger = get_logger(__name__)

_CALENDAR_WRITE_DELAY = 0.15  # Stay under 10 req/sec burst limit


def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=settings.GOOGLE_CALENDAR_SCOPES,
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _build_event_body(task: CleaningTask, prop: Property) -> dict:
    date_str = task.cleaning_date.isoformat()
    start_dt = f"{date_str}T{task.cleaning_start_time}:00"
    end_dt = f"{date_str}T{task.cleaning_end_time}:00"

    summary = f"Clean: {task.property_name}"
    if task.is_same_day_turnover:
        summary = f"⚡ TURNOVER: {task.property_name}"

    description_lines = [
        f"Cleaner: {task.cleaner_name}",
        f"Property: {task.property_name}",
        f"Address: {prop.address}",
        f"Cleaning Fee: ${task.cleaning_fee:.2f}",
        "",
    ]
    if task.is_same_day_turnover:
        description_lines += [
            "⚠️  SAME-DAY TURNOVER — new guests arrive same day.",
            f"Next check-in: {task.next_checkin_date}",
            f"Next guest: {task.next_guest_name or 'Unknown'}",
            f"Must finish by: {task.cleaning_end_time}",
        ]

    return {
        "summary": summary,
        "description": "\n".join(description_lines),
        "location": prop.address,
        "start": {"dateTime": start_dt, "timeZone": "America/New_York"},
        "end": {"dateTime": end_dt, "timeZone": "America/New_York"},
        "colorId": "11" if task.is_same_day_turnover else "2",  # Red for turnover, green otherwise
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
                {"method": "email", "minutes": 1440},  # 24h before
            ],
        },
    }


def sync_task(task: CleaningTask, prop: Property, airtable_update_fn) -> CleaningTask:
    """
    Create, update, or delete a Google Calendar event for a cleaning task.
    Calls airtable_update_fn to persist the event ID back to Airtable.
    """
    if not prop.google_calendar_id:
        logger.warning("Property '%s' has no Google Calendar ID — skipping", prop.name)
        return task

    service = _get_service()
    calendar_id = prop.google_calendar_id
    time.sleep(_CALENDAR_WRITE_DELAY)

    # --- Cancelled task: delete the calendar event ---
    if task.status == "Cancelled":
        if task.google_calendar_event_id:
            try:
                service.events().delete(
                    calendarId=calendar_id,
                    eventId=task.google_calendar_event_id,
                ).execute()
                task.google_calendar_event_id = None
                airtable_update_fn(task.airtable_id, task)
                logger.info("Deleted calendar event for cancelled task %s", task.airtable_id)
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning("Calendar event already gone for task %s", task.airtable_id)
                    task.google_calendar_event_id = None
                    airtable_update_fn(task.airtable_id, task)
                else:
                    logger.error("Failed to delete calendar event: %s", e)
        return task

    event_body = _build_event_body(task, prop)

    # --- Existing event: try update ---
    if task.google_calendar_event_id:
        try:
            service.events().update(
                calendarId=calendar_id,
                eventId=task.google_calendar_event_id,
                body=event_body,
            ).execute()
            logger.info("Updated calendar event for task %s", task.airtable_id)
            return task
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(
                    "Calendar event %s not found — will re-create", task.google_calendar_event_id
                )
                task.google_calendar_event_id = None
            else:
                logger.error("Failed to update calendar event: %s", e)
                return task

    # --- No existing event: create ---
    try:
        result = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
        ).execute()
        task.google_calendar_event_id = result["id"]
        airtable_update_fn(task.airtable_id, task)
        logger.info(
            "Created calendar event %s for task %s", task.google_calendar_event_id, task.airtable_id
        )
    except HttpError as e:
        logger.error("Failed to create calendar event for task %s: %s", task.airtable_id, e)

    return task
