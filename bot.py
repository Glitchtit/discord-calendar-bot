import os
import requests
import schedule
import time
from datetime import datetime, timedelta
from dateutil import tz

from google.oauth2 import service_account
from googleapiclient.discovery import build

# 1. Environment Variables / Configuration
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_ID = os.environ.get("CALENDAR_ID")

# Path to your service account JSON
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Build the Google Calendar API client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)


def post_to_discord(message: str):
    """
    Sends a plain text message to the Discord channel via webhook.
    """
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL is not set.")
        return

    payload = {"content": message}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"Failed to send message. Status: {resp.status_code} - {resp.text}")


def format_event(event) -> str:
    """
    Return a string describing the event (date/time + summary),
    converting times to the local system timezone.
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))

    summary = event.get("summary", "No Title")

    # Convert from UTC to local time if it's a datetime
    if "T" in start:  # Means it's dateTime, not all-day
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        start_local = start_dt.astimezone(tz.tzlocal())
        start_str = start_local.strftime("%Y-%m-%d %H:%M")
    else:
        # All-day event
        start_str = start

    if "T" in end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        end_local = end_dt.astimezone(tz.tzlocal())
        end_str = end_local.strftime("%Y-%m-%d %H:%M")
    else:
        end_str = end

    return f"- {summary} ({start_str} to {end_str})"


def get_events_for_day(date_obj):
    """
    Retrieve all events for a single day from 00:00 to 23:59 local time (converted to UTC).
    """
    # Convert local date_obj to an ISO string and define timeMin and timeMax in UTC
    start_of_day_utc = date_obj.isoformat() + "T00:00:00Z"
    end_of_day_utc = date_obj.isoformat() + "T23:59:59Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_of_day_utc,
        timeMax=end_of_day_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def get_events_for_week(monday_date):
    """
    Retrieve events for the week starting with monday_date (Mon-Sun).
    """
    start_of_week_utc = monday_date.isoformat() + "T00:00:00Z"
    end_of_week = monday_date + timedelta(days=6)
    end_of_week_utc = end_of_week.isoformat() + "T23:59:59Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_of_week_utc,
        timeMax=end_of_week_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def post_todays_happenings():
    today = datetime.now(tz=tz.tzlocal()).date()
    events = get_events_for_day(today)

    if not events:
        message = "No events scheduled for today."
    else:
        lines = ["**Today’s Happenings:**"]
        for event in events:
            lines.append(format_event(event))
        message = "\n".join(lines)

    post_to_discord(message)


def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    # Calculate Monday of the current week (weekday() returns 0 for Monday)
    monday = now - timedelta(days=now.weekday())

    events = get_events_for_week(monday)
    if not events:
        message = "No events scheduled for this week."
    else:
        lines = ["**This Week’s Happenings:**"]
        for event in events:
            lines.append(format_event(event))
        message = "\n".join(lines)

    post_to_discord(message)


# SCHEDULING TASKS
# ---------------------------------------
# Post "Today’s Happenings" every day at 08:00 local time
schedule.every().day.at("08:00").do(post_todays_happenings)

# Post "This Week’s Happenings" every Monday at 09:00 local time
schedule.every().monday.at("09:00").do(post_weeks_happenings)

if __name__ == "__main__":
    print("Bot started. Waiting for scheduled tasks...")
    while True:
        schedule.run_pending()
        time.sleep(30)  # Check every 30 seconds
