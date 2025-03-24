import os
import requests
import schedule
import time
import json
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

EVENTS_FILE = "events.json"

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

def load_previous_events():
    """
    Load the previous events from the JSON file.
    """
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_current_events(events):
    """
    Save the current events to the JSON file.
    """
    with open(EVENTS_FILE, "w") as f:
        json.dump(events, f)

def detect_changes(previous_events, current_events):
    """
    Detect changes between previous and current events.
    """
    changes = []
    previous_event_ids = {event["id"] for event in previous_events}
    current_event_ids = {event["id"] for event in current_events}

    added_events = [event for event in current_events if event["id"] not in previous_event_ids]
    removed_events = [event for event in previous_events if event["id"] not in current_event_ids]
    common_event_ids = previous_event_ids & current_event_ids

    for event_id in common_event_ids:
        prev_event = next(event for event in previous_events if event["id"] == event_id)
        curr_event = next(event for event in current_events if event["id"] == event_id)
        if prev_event != curr_event:
            changes.append(f"Event changed: {format_event(curr_event)}")

    for event in added_events:
        changes.append(f"Event added: {format_event(event)}")

    for event in removed_events:
        changes.append(f"Event removed: {format_event(event)}")

    return changes

def post_changes_to_discord(changes):
    """
    Post detected changes to Discord.
    """
    if changes:
        message = "**Changes Detected:**\n" + "\n".join(changes)
        post_to_discord(message)
        print("[DEBUG] Changes detected and posted to Discord.")
    else:
        print("[DEBUG] No changes detected.")

def post_todays_happenings():
    """
    Retrieve today's events and post them to Discord.
    """
    print("[DEBUG] post_todays_happenings() called. Attempting to fetch today's events.")
    today = datetime.now(tz=tz.tzlocal()).date()
    events = get_events_for_day(today)
    previous_events = load_previous_events().get(str(today), [])

    changes = detect_changes(previous_events, events)
    post_changes_to_discord(changes)

    if not events:
        message = "No events scheduled for today."
    else:
        lines = ["**Today’s Happenings:**"]
        for e in events:
            lines.append(format_event(e))
        message = "\n".join(lines)

    post_to_discord(message)
    save_current_events({str(today): events})
    print("[DEBUG] post_todays_happenings() finished. Check Discord for today's post.")

def post_weeks_happenings():
    """
    Retrieve events for Monday–Sunday of the current week and post them.
    """
    print("[DEBUG] post_weeks_happenings() called. Attempting to fetch this week's events.")
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())  # 0=Monday, 6=Sunday
    events = get_events_for_week(monday)
    previous_events = load_previous_events().get(str(monday), [])

    changes = detect_changes(previous_events, events)
    post_changes_to_discord(changes)

    if not events:
        message = "No events scheduled for this week."
    else:
        lines = ["**This Week’s Happenings:**"]
        for e in events:
            lines.append(format_event(e))
        message = "\n".join(lines)

    post_to_discord(message)
    save_current_events({str(monday): events})
    print("[DEBUG] post_weeks_happenings() finished. Check Discord for weekly post.")

def save_current_events_for_date(date_str, events):
    """
    Save (merge) the current events for a specific date into the JSON file
    without overwriting other dates.
    """
    existing_data = load_previous_events()  # load the entire dictionary
    existing_data[date_str] = events        # update this specific date
    with open(EVENTS_FILE, "w") as f:
        json.dump(existing_data, f)

def check_for_changes():
    print("[DEBUG] check_for_changes() called. Checking for changes in events.")
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())

    # 1. Check today's events
    today_events = get_events_for_day(today)
    all_previous = load_previous_events()  # load all stored data
    previous_today_events = all_previous.get(str(today), [])
    today_changes = detect_changes(previous_today_events, today_events)
    post_changes_to_discord(today_changes)
    save_current_events_for_date(str(today), today_events)

    # 2. Check this week's events
    week_events = get_events_for_week(monday)
    all_previous = load_previous_events()  # reload the file in case we just changed something
    previous_week_events = all_previous.get(str(monday), [])
    week_changes = detect_changes(previous_week_events, week_events)
    post_changes_to_discord(week_changes)
    save_current_events_for_date(str(monday), week_events)

    print("[DEBUG] check_for_changes() finished.")


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

    print("[DEBUG] Entering schedule loop. Will check for scheduled tasks every 60 seconds.")
    while True:
        schedule.run_pending()
        print("[DEBUG] Checking for changes in events with loop...")
        check_for_changes()
        time.sleep(60)
