"""
Add a single property to Airtable (iCal-based).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyairtable import Api
from config import settings

api = Api(settings.AIRTABLE_API_KEY)
table = api.table(settings.AIRTABLE_BASE_ID, "Properties")

properties = [
    {
        "Name": "511 S K St Lake Worth",
        "ical URL": "https://hostex.io/web/ical/12595102.ics?t=20921b399d3fe2fc96323e62d768442f",
        "Address": "511 S K St, Lake Worth, FL",
        "Default Checkout Time": "11:00",
        "Default Checkin Time": "15:00",
        "Turnover Time Hours": 4,
        "Active ": "Checked",
    },
]

for p in properties:
    record = table.create(p)
    print(f"Created: {record['id']} — {record['fields']['Name']}")
