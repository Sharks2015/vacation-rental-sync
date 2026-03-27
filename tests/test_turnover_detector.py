"""Tests for same-day turnover detection."""
from datetime import date
from unittest.mock import MagicMock

import pytest

from models.booking import Booking
from models.cleaning_task import CleaningTask
from sync.turnover_detector import detect_and_flag


def make_booking(uid, checkin, checkout, status="Confirmed"):
    return Booking(
        uid=uid,
        property_id="recPROP1",
        property_name="Blue House",
        guest_name=f"Guest {uid}",
        checkin=date.fromisoformat(checkin),
        checkout=date.fromisoformat(checkout),
        status=status,
    )


def make_task(uid, cleaning_date, airtable_id=None):
    return CleaningTask(
        airtable_id=airtable_id or f"recTASK_{uid}",
        property_id="recPROP1",
        property_name="Blue House",
        booking_uid=uid,
        booking_airtable_id="recBOOK1",
        cleaning_date=date.fromisoformat(cleaning_date),
        cleaning_start_time="11:00",
        cleaning_end_time="14:00",
        cleaner_name="Ana",
        cleaner_phone="+15550001234",
        cleaning_fee=150.0,
    )


def test_same_day_turnover_detected():
    bookings = [
        make_booking("uid-1", "2026-04-01", "2026-04-05"),
        make_booking("uid-2", "2026-04-05", "2026-04-08"),
    ]
    task1 = make_task("uid-1", "2026-04-05")
    tasks = {"uid-1": task1}

    def get_task(uid):
        return tasks.get(uid)

    updated = []

    def update_task(airtable_id, task):
        updated.append(task)
        return task

    result = detect_and_flag(bookings, get_task, update_task)

    assert len(result) == 1
    assert result[0].is_same_day_turnover is True
    assert result[0].next_checkin_date == date(2026, 4, 5)


def test_no_turnover_with_gap():
    bookings = [
        make_booking("uid-1", "2026-04-01", "2026-04-04"),
        make_booking("uid-2", "2026-04-05", "2026-04-08"),  # 1-day gap
    ]
    task1 = make_task("uid-1", "2026-04-04")

    def get_task(uid):
        return task1 if uid == "uid-1" else None

    def update_task(airtable_id, task):
        return task

    result = detect_and_flag(bookings, get_task, update_task)
    assert len(result) == 0


def test_cancelled_bookings_excluded():
    bookings = [
        make_booking("uid-1", "2026-04-01", "2026-04-05"),
        make_booking("uid-2", "2026-04-05", "2026-04-08", status="Cancelled"),
    ]
    task1 = make_task("uid-1", "2026-04-05")

    def get_task(uid):
        return task1 if uid == "uid-1" else None

    def update_task(airtable_id, task):
        return task

    result = detect_and_flag(bookings, get_task, update_task)
    assert len(result) == 0
