import os
import requests
import schedule
import time
import json
from datetime import datetime, timedelta
from dateutil import tz

from google.oauth2 import service_account
from googleapiclient.discovery import build

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
CALENDAR_ID = os.environ.get("CALENDAR_ID")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)

EVENTS_FILE = "events.json"

#
# 1) HELPER: LOAD AND SAVE EVENT DICTIONARY
#
def load_previous_events():
    """
    Load the entire dictionary of previously saved events from the JSON file.
    Keys: date strings, e.g. '2025-03-27'
    Values: list of event objects from that day/week
    """
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_current_events_for_date(date_str, events):
    """
    Merge the given 'events' into the events.json dictionary under the key date_str.
    This way we do NOT overwrite data for other dates.
    """
    existing_data = load_previous_events()
    existing_data[date_str] = events  # store/replace only this date's events
    with open(EVENTS_FILE, "w") as f:
        json.dump(existing_data, f)

#
# 2) HELPER: DISCORD + FORMATTING
#
def post_to_discord(message: str):
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
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "No Title")

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

#
# 3) FETCH EVENTS
#
def get_events_for_day(date_obj):
    print(f"[DEBUG] get_events_for_day() called for date: {date_obj}")
    start_utc = date_obj.isoformat() + "T00:00:00Z"
    end_utc = date_obj.isoformat() + "T23:59:59Z"
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])

def get_events_for_week(monday_date):
    print(f"[DEBUG] get_events_for_week() called for week starting: {monday_date}")
    start_utc = monday_date.isoformat() + "T00:00:00Z"
    end_of_week = monday_date + timedelta(days=6)
    end_utc = end_of_week.isoformat() + "T23:59:59Z"
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])

#
# 4) DETECT CHANGES
#
def detect_changes(previous_events, current_events):
    changes = []
    prev_ids = {e["id"] for e in previous_events}
    curr_ids = {e["id"] for e in current_events}

    added = [e for e in current_events if e["id"] not in prev_ids]
    removed = [e for e in previous_events if e["id"] not in curr_ids]

    # If you want to detect updates (e.g., changed times) for events with the same ID:
    # common_ids = prev_ids & curr_ids
    # for cid in common_ids:
    #     p_event = next(e for e in previous_events if e["id"] == cid)
    #     c_event = next(e for e in current_events if e["id"] == cid)
    #     if p_event != c_event:
    #         changes.append(f"Event changed: {format_event(c_event)}")

    for e in added:
        changes.append(f"Event added: {format_event(e)}")
    for e in removed:
        changes.append(f"Event removed: {format_event(e)}")

    return changes

def post_changes_to_discord(changes):
    if changes:
        msg = "**Changes Detected:**\n" + "\n".join(changes)
        post_to_discord(msg)
        print("[DEBUG] Changes detected and posted to Discord.")
    else:
        print("[DEBUG] No changes detected.")

#
# 5) DAILY + WEEKLY POSTS
#
def post_todays_happenings():
    print("[DEBUG] post_todays_happenings() called.")
    today = datetime.now(tz=tz.tzlocal()).date()

    # 1. Load current + previous events
    previous_all = load_previous_events()
    previous_today_events = previous_all.get(str(today), [])
    today_events = get_events_for_day(today)

    # 2. Detect changes
    changes = detect_changes(previous_today_events, today_events)
    post_changes_to_discord(changes)

    # 3. Post summary
    if not today_events:
        msg = "No events scheduled for today."
    else:
        lines = ["**Today’s Happenings:**"] + [format_event(e) for e in today_events]
        msg = "\n".join(lines)
    post_to_discord(msg)

    # 4. Merge (not overwrite!) the JSON for date=today
    save_current_events_for_date(str(today), today_events)
    print("[DEBUG] post_todays_happenings() finished.")

def post_weeks_happenings():
    print("[DEBUG] post_weeks_happenings() called.")
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())

    # 1. Load current + previous
    prev_all = load_previous_events()
    previous_week_events = prev_all.get(str(monday), [])
    week_events = get_events_for_week(monday)

    # 2. Detect changes
    changes = detect_changes(previous_week_events, week_events)
    post_changes_to_discord(changes)

    # 3. Post summary
    if not week_events:
        msg = "No events scheduled for this week."
    else:
        lines = ["**This Week’s Happenings:**"] + [format_event(e) for e in week_events]
        msg = "\n".join(lines)
    post_to_discord(msg)

    # 4. Merge the data for date=monday
    save_current_events_for_date(str(monday), week_events)
    print("[DEBUG] post_weeks_happenings() finished.")

#
# 6) REAL-TIME CHANGES (MINUTE-BY-MINUTE)
#
def check_for_changes():
    """
    Called once a minute to see if anything changed
    for today or for this week's Monday.
    """
    print("[DEBUG] check_for_changes() called.")
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())

    # Check today's events
    prev_data = load_previous_events()
    prev_today = prev_data.get(str(today), [])
    today_events = get_events_for_day(today)
    today_changes = detect_changes(prev_today, today_events)
    post_changes_to_discord(today_changes)
    save_current_events_for_date(str(today), today_events)

    # Check this week's events
    prev_data = load_previous_events()
    prev_week = prev_data.get(str(monday), [])
    week_events = get_events_for_week(monday)
    week_changes = detect_changes(prev_week, week_events)
    post_changes_to_discord(week_changes)
    save_current_events_for_date(str(monday), week_events)

    print("[DEBUG] check_for_changes() finished.")

#
# 7) SCHEDULING
#
schedule.every().day.at("08:00").do(post_todays_happenings)
schedule.every().monday.at("09:00").do(post_weeks_happenings)

if __name__ == "__main__":
    print("[DEBUG] Bot started. Immediately posting today's and this week's happenings.")
    post_todays_happenings()
    post_weeks_happenings()

    print("[DEBUG] Entering schedule loop. Will check for scheduled tasks every 60 seconds.")
    while True:
        schedule.run_pending()
        print("[DEBUG] Checking for changes in events with loop...")
        check_for_changes()   # If you really want minute-by-minute detection
        time.sleep(60)
