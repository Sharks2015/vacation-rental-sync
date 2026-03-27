"""
Delete all Lodgify-based properties and their linked bookings + cleaning tasks from Airtable.
Keeps iCal-based properties (those without a Lodgify Property ID).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyairtable import Api
from config import settings

api = Api(settings.AIRTABLE_API_KEY)

props_table    = api.table(settings.AIRTABLE_BASE_ID, "Properties")
bookings_table = api.table(settings.AIRTABLE_BASE_ID, "Bookings")
tasks_table    = api.table(settings.AIRTABLE_BASE_ID, "Cleaning Tasks")

# 1. Find Lodgify properties
all_props = props_table.all()
lodgify_props = [r for r in all_props if r["fields"].get("Lodgify Property ID")]
lodgify_ids   = {r["id"] for r in lodgify_props}

print(f"Found {len(lodgify_props)} Lodgify properties to delete:")
for r in lodgify_props:
    print(f"  - {r['fields'].get('Name', '?')} (Lodgify ID: {r['fields'].get('Lodgify Property ID')})")

if not lodgify_props:
    print("Nothing to delete.")
    sys.exit(0)

# 2. Delete linked bookings
all_bookings = bookings_table.all()
booking_ids_to_delete = [
    r["id"] for r in all_bookings
    if any(pid in lodgify_ids for pid in (r["fields"].get("Property") or []))
]
print(f"\nDeleting {len(booking_ids_to_delete)} linked bookings...")
for rid in booking_ids_to_delete:
    bookings_table.delete(rid)

# 3. Delete linked cleaning tasks
all_tasks = tasks_table.all()
task_ids_to_delete = [
    r["id"] for r in all_tasks
    if any(pid in lodgify_ids for pid in (r["fields"].get("Property") or []))
]
print(f"Deleting {len(task_ids_to_delete)} linked cleaning tasks...")
for rid in task_ids_to_delete:
    tasks_table.delete(rid)

# 4. Delete the properties themselves
print(f"Deleting {len(lodgify_props)} properties...")
for r in lodgify_props:
    props_table.delete(r["id"])

print("\nDone. All Lodgify properties, bookings, and tasks have been removed.")
