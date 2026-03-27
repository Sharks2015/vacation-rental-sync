"""
Add a single property to Airtable (iCal-based).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyairtable import Api
from config import settings

api = Api(settings.AIRTABLE_API_KEY)
table = api.table(settings.AIRTABLE_BASE_ID, "Properties")

record = table.create({
    "Name": "258 Avalon Ave Lauderdale-By-The-Sea",
    "ical URL": "https://www.lodgify.com/7b999f93-bb48-4018-84a2-30577b4db741.ics",
    "Default Checkout Time": "10:00",
    "Default Checkin Time": "16:00",
    "Turnover Time Hours": 3,
})

print(f"Created: {record['id']} — {record['fields']['Name']}")
