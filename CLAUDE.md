# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This System Does

Automates vacation rental cleaning scheduling by:
1. Polling Airbnb iCal feeds every 2 hours
2. Diffing against Airtable to detect new/modified/cancelled bookings
3. Creating and updating cleaning tasks in Airtable
4. Detecting same-day turnovers (checkout + new check-in on same day)
5. Syncing cleaning events to Google Calendar
6. Sending SMS notifications to cleaners via Twilio

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with real credentials
```

**Google Calendar auth:** uses a Service Account JSON file (no browser OAuth). Set `GOOGLE_SERVICE_ACCOUNT_FILE` to the path of the downloaded JSON. Share each property's calendar with the service account email ("Make changes to events" permission).

## Running

```bash
# Run a full sync now
python main.py

# Run tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_turnover_detector.py -v
```

**Cron (every 2 hours):**
```
0 */2 * * * /path/to/venv/bin/python /path/to/vacation-rental-sync/main.py >> /var/log/rental-sync.log 2>&1
```

## Architecture

```
main.py  →  sync/  →  integrations/
              |             |
              |       airtable_client.py   (all Airtable CRUD)
              |       google_calendar.py   (Calendar API)
              |       twilio_sms.py        (SMS via Twilio)
              |
         ical_fetcher.py       (HTTP fetch + parse iCal)
         booking_sync.py       (diff algorithm — core logic)
         cleaning_scheduler.py (create/update/cancel tasks)
         turnover_detector.py  (same-day turnover flagging)
```

**Data flow order in main.py (order matters):**
1. Fetch iCal → 2. Diff vs Airtable → 3. Upsert bookings → 4. Schedule tasks → 5. Detect turnovers → 6. Sync Calendar → 7. Send SMS

Turnover detection must run after cancellations are processed (step 4), or cancelled bookings will be included in the consecutive-booking check.

## Airtable Tables

Three tables in one base:
- **Properties** — one record per rental unit (iCal URL, cleaner info, calendar ID)
- **Bookings** — one record per Airbnb reservation, keyed by `Booking UID` (iCal VEVENT UID)
- **Cleaning Tasks** — one record per checkout, linked to the Booking that triggered it

`Booking UID` is the stable dedup key. Never rely on Airtable record IDs for deduplication across sync runs.

## Key Invariants

- **`main.py` is fully idempotent** — re-running produces no duplicates and no extra SMS
- **Completed tasks are never modified** — `cleaning_scheduler.py` checks `status == "Completed"` before any update
- **SMS is gated by `task.notified`** — set to `True` after sending, persisted to Airtable immediately
- **Blocked/unavailable Airbnb events** (SUMMARY contains "Not available") never generate cleaning tasks
- **Historical checkouts are skipped** — tasks are only created for `checkout >= today()`
- **iCal fetch failures are non-fatal** — if a URL fails, that property is skipped for the current run; existing Airtable data is not touched

## Airtable Field Names (exact strings used in API calls)

Properties table: `Name`, `Address`, `iCal URL`, `Cleaner Name`, `Cleaner Phone`, `Cleaning Fee`, `Turnover Time Hours`, `Google Calendar ID`, `Active`, `Default Checkout Time`, `Default Checkin Time`, `Property Manager Email`, `Property Manager Phone`

Bookings table: `Booking UID`, `Property`, `Guest Name`, `Check-in Date`, `Check-out Date`, `Status`, `Raw iCal Summary`, `Last Synced At`

Cleaning Tasks table: `Property`, `Booking`, `Booking UID`, `Cleaning Date`, `Cleaning Start Time`, `Cleaning End Time`, `Cleaner`, `Cleaner Phone`, `Cleaning Fee`, `Is Same-Day Turnover`, `Next Check-in Date`, `Next Guest Name`, `Status`, `Google Calendar Event ID`, `Notified`

Field names must match exactly — Airtable API is case-sensitive.
