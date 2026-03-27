"""Tests for booking diff logic."""
from datetime import date

import pytest

from models.booking import Booking
from sync.booking_sync import diff


def make_booking(uid, checkin, checkout, guest="Guest", airtable_id=None, status="Confirmed"):
    return Booking(
        uid=uid,
        property_id="recPROP1",
        property_name="Blue House",
        guest_name=guest,
        checkin=date.fromisoformat(checkin),
        checkout=date.fromisoformat(checkout),
        status=status,
        airtable_id=airtable_id,
    )


def test_new_booking_detected():
    fetched = [make_booking("uid-1", "2026-04-01", "2026-04-05")]
    existing = []
    result = diff(fetched, existing)
    assert len(result.new) == 1
    assert result.new[0].uid == "uid-1"
    assert result.modified == []
    assert result.cancelled == []


def test_cancelled_booking_detected():
    fetched = []
    existing = [make_booking("uid-1", "2026-04-01", "2026-04-05", airtable_id="recBOOK1")]
    result = diff(fetched, existing)
    assert len(result.cancelled) == 1
    assert result.cancelled[0].status == "Cancelled"


def test_modified_booking_detected():
    fetched = [make_booking("uid-1", "2026-04-01", "2026-04-06")]  # checkout changed
    existing = [make_booking("uid-1", "2026-04-01", "2026-04-05", airtable_id="recBOOK1")]
    result = diff(fetched, existing)
    assert len(result.modified) == 1
    assert result.modified[0].checkout == date(2026, 4, 6)
    # airtable_id carried forward
    assert result.modified[0].airtable_id == "recBOOK1"


def test_unchanged_booking():
    b = make_booking("uid-1", "2026-04-01", "2026-04-05", airtable_id="recBOOK1")
    result = diff([b], [b])
    assert result.unchanged[0].uid == "uid-1"
    assert result.new == []
    assert result.modified == []
    assert result.cancelled == []


def test_already_cancelled_not_re_cancelled():
    existing = [make_booking("uid-1", "2026-04-01", "2026-04-05", airtable_id="recBOOK1", status="Cancelled")]
    result = diff([], existing)
    assert result.cancelled == []
