import os
from dotenv import load_dotenv

load_dotenv()

# Lodgify
LODGIFY_API_KEY = os.getenv("LODGIFY_API_KEY", "")

# Airtable
AIRTABLE_API_KEY = os.environ["AIRTABLE_API_KEY"]
AIRTABLE_BASE_ID = os.environ["AIRTABLE_BASE_ID"]
AIRTABLE_PROPERTIES_TABLE = "Properties"
AIRTABLE_BOOKINGS_TABLE = "Bookings"
AIRTABLE_TASKS_TABLE = "Cleaning Tasks"

# Google Calendar (optional until configured)
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Twilio (optional until configured)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")

# Sync behavior
SYNC_LOOKAHEAD_DAYS = int(os.getenv("SYNC_LOOKAHEAD_DAYS", "90"))
SYNC_LOOKBACK_DAYS = int(os.getenv("SYNC_LOOKBACK_DAYS", "1"))
