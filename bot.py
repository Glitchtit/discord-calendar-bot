import os
import requests
import schedule
import time
from datetime import datetime, timedelta
from dateutil import tz

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Read environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_ID = os.environ.get("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

# Scope for read-only access to Google Calendar
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Build the Google Calendar API client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)

def post_to_discord(message: str):
    """
    Sends a message to the Discord channel via webhook.
    """
    print("[DEBUG] post_to_discord() called. Sending message to Discord...")
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] DISCORD_WEBHOOK_URL is not set. Cannot send message.")
        return

    payload = {"content": message}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Failed to send message. Status: {resp.status_code} - {resp.text}")
    else:
        print("[DEBUG] Message sent to Discord successfully.")

def format_event(event) -> str:
    """
    Return a string describing the event (date/time + summary).
    Converts times to local timezone if it's a time-based event.
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "No Title")

    # If there's a 'T', assume it's a dateTime; otherwise it's an all-day event
    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        start_local = start_dt.astimezone(tz.tzlocal())
        start_str = start_local.strftime("%Y-%m-%d %H:%M")
    else:
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
    Fetch events for a single day (00:00 to 23:59 local time).
    """
    print(f"[DEBUG] get_events_for_day() called for date: {date_obj}")
    start_utc = date_obj.isoformat() + "T00:00:00Z"
    end_utc = date_obj.isoformat() + "T23:59:59Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return events_result.get("items", [])

def get_events_for_week(monday_date):
    """
    Fetch events for the week starting with monday_date (Mon-Sun).
    """
    print(f"[DEBUG] get_events_for_week() called for week starting: {monday_date}")
    start_utc = monday_date.isoformat() + "T00:00:00Z"
    end_of_week = monday_date + timedelta(days=6)
    end_utc = end_of_week.isoformat() + "T23:59:59Z"

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return events_result.get("items", [])

def post_todays_happenings():
    """
    Retrieve today's events and post them to Discord.
    """
    print("[DEBUG] post_todays_happenings() called. Attempting to fetch today's events.")
    today = datetime.now(tz=tz.tzlocal()).date()
    events = get_events_for_day(today)
    if not events:
        message = "No events scheduled for today."
    else:
        lines = ["**Today’s Happenings:**"]
        for e in events:
            lines.append(format_event(e))
        message = "\n".join(lines)

    post_to_discord(message)
    print("[DEBUG] post_todays_happenings() finished. Check Discord for today's post.")

def post_weeks_happenings():
    """
    Retrieve events for Monday–Sunday of the current week and post them.
    """
    print("[DEBUG] post_weeks_happenings() called. Attempting to fetch this week's events.")
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())  # 0=Monday, 6=Sunday
    events = get_events_for_week(monday)
    if not events:
        message = "No events scheduled for this week."
    else:
        lines = ["**This Week’s Happenings:**"]
        for e in events:
            lines.append(format_event(e))
        message = "\n".join(lines)

    post_to_discord(message)
    print("[DEBUG] post_weeks_happenings() finished. Check Discord for weekly post.")

# ------------------------
# SCHEDULING
# ------------------------
# Post "Today’s Happenings" daily at 08:00 local time
schedule.every().day.at("08:00").do(post_todays_happenings)
# Post "This Week’s Happenings" every Monday at 09:00 local time
schedule.every().monday.at("09:00").do(post_weeks_happenings)

if __name__ == "__main__":
    print("[DEBUG] Bot started. Immediately posting today's and this week's happenings.")
    # Immediately post today's and weekly happenings upon startup:
    post_todays_happenings()
    post_weeks_happenings()

    print("[DEBUG] Entering schedule loop. Will check for scheduled tasks every 30 seconds.")
    while True:
        schedule.run_pending()
        time.sleep(30)
