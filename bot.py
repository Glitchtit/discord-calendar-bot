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
# 1. LOADING / SAVING EVENTS
#
def load_previous_events():
    """
    Returns a dictionary of all stored events, with keys for each category/date,
    e.g. {
        "DAILY_YYYY-MM-DD": [ ...list of events... ],
        "WEEK_YYYY-MM-DD":  [ ...list of events... ]
    }
    """
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}

def save_current_events_for_key(key, events):
    """
    Merges the list of 'events' into the JSON under 'key'.
    This prevents overwriting other keys (daily vs. weekly).
    """
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w") as f:
        json.dump(all_data, f)

#
# 2. DISCORD EMBEDS + FORMATTING
#
def post_embed_to_discord(title: str, description: str, color: int = 5814783):
    """
    Sends an embedded message to Discord with a title and description.
    """
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color
            }
        ]
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord post successful.")

def format_event(event) -> str:
    """
    Pretty-print an event with local times.
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end   = event["end"].get("dateTime", event["end"].get("date"))
    title = event.get("summary", "No Title")
    location = event.get("location", "")

    # Convert dateTime to local time if "T" is present
    if "T" in start:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        start_str = start_dt.strftime("%Y-%m-%d %H:%M")
    else:
        start_str = start

    if "T" in end:
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    else:
        end_str = end

    if location:
        return f"- {title} ({start_str} to {end_str}, at {location})"
    else:
        return f"- {title} ({start_str} to {end_str})"

#
# 3. FETCH EVENTS
#
def get_events_for_day(date_obj):
    start_utc = date_obj.isoformat() + "T00:00:00Z"
    end_utc   = date_obj.isoformat() + "T23:59:59Z"

    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

def get_events_for_week(monday_date):
    start_utc = monday_date.isoformat() + "T00:00:00Z"
    end_of_week = monday_date + timedelta(days=6)
    end_utc   = end_of_week.isoformat() + "T23:59:59Z"

    result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

#
# 4. DETECT CHANGES (ADDED, REMOVED, OR MODIFIED EVENTS)
#
def extract_comparable_fields(event):
    """
    Extract key fields to compare events.
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)

def detect_changes(old_events, new_events):
    """
    Compare old vs. new event lists.
    Detect added, removed, and modified (changed) events.
    """
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    # Added events
    added_ids = new_ids - old_ids
    for eid in added_ids:
        changes.append(f"Event added: {format_event(new_dict[eid])}")

    # Removed events
    removed_ids = old_ids - new_ids
    for eid in removed_ids:
        changes.append(f"Event removed: {format_event(old_dict[eid])}")

    # Changed events: same ID but differing key fields (like time, title, etc.)
    common_ids = old_ids & new_ids
    for eid in common_ids:
        old_fields = extract_comparable_fields(old_dict[eid])
        new_fields = extract_comparable_fields(new_dict[eid])
        if old_fields != new_fields:
            changes.append(
                f"Event changed:\nOLD: {format_event(old_dict[eid])}\nNEW: {format_event(new_dict[eid])}"
            )
    return changes

def post_changes_embed(changes):
    """
    If there are changes, send them in an embedded message.
    """
    if changes:
        description = "\n".join(changes)
        post_embed_to_discord("Changes Detected", description)
    else:
        print("[DEBUG] No changes detected (no embed posted).")

#
# 5. DAILY SUMMARY (SCHEDULED)
#
def post_todays_happenings():
    """
    Runs once a day (08:00).
    Posts today's events in an embed and saves the current state.
    """
    today = datetime.now(tz=tz.tzlocal()).date()
    daily_key = f"DAILY_{today}"

    all_data = load_previous_events()
    old_daily_events = all_data.get(daily_key, [])

    today_events = get_events_for_day(today)

    # Check & post changes (added, removed, or modified)
    changes = detect_changes(old_daily_events, today_events)
    post_changes_embed(changes)

    # Then post daily summary
    if today_events:
        lines = [format_event(e) for e in today_events]
        description = "\n".join(lines)
        post_embed_to_discord("Today’s Happenings", description)
    else:
        post_embed_to_discord("Today’s Happenings", "No events scheduled for today.")

    # Save current state
    save_current_events_for_key(daily_key, today_events)

#
# 6. WEEKLY SUMMARY (SCHEDULED)
#
def post_weeks_happenings():
    """
    Runs once a week (Monday 09:00).
    Posts the week's events in an embed and saves the current state.
    """
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    week_key = f"WEEK_{monday}"

    all_data = load_previous_events()
    old_week_events = all_data.get(week_key, [])

    week_events = get_events_for_week(monday)

    # Check & post changes
    changes = detect_changes(old_week_events, week_events)
    post_changes_embed(changes)

    # Then post weekly summary
    if week_events:
        lines = [format_event(e) for e in week_events]
        description = "\n".join(lines)
        post_embed_to_discord("This Week’s Happenings", description)
    else:
        post_embed_to_discord("This Week’s Happenings", "No events scheduled for this week.")

    # Save current state
    save_current_events_for_key(week_key, week_events)

#
# 7. REAL-TIME CHANGES EVERY MINUTE
#
def check_for_changes():
    """
    Check daily and weekly events each minute, posting only if there are any changes.
    """
    print("[DEBUG] check_for_changes() called.")

    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())

    # Check changes for today's events
    daily_key = f"DAILY_{today}"
    all_data = load_previous_events()
    old_daily_events = all_data.get(daily_key, [])
    today_events = get_events_for_day(today)
    daily_changes = detect_changes(old_daily_events, today_events)

    if daily_changes:
        post_changes_embed(daily_changes)
    save_current_events_for_key(daily_key, today_events)

    # Check changes for the week's events
    week_key = f"WEEK_{monday}"
    all_data = load_previous_events()  # Reload data in case it changed
    old_week_events = all_data.get(week_key, [])
    week_events = get_events_for_week(monday)
    weekly_changes = detect_changes(old_week_events, week_events)

    if weekly_changes:
        post_changes_embed(weekly_changes)
    save_current_events_for_key(week_key, week_events)

    print("[DEBUG] check_for_changes() finished.")

#
# 8. SCHEDULE
#
schedule.every().day.at("08:00").do(post_todays_happenings)
schedule.every().monday.at("09:00").do(post_weeks_happenings)

if __name__ == "__main__":
    print("[DEBUG] Bot started. Immediately posting today's and this week's happenings.")
    post_todays_happenings()
    post_weeks_happenings()

    print("[DEBUG] Entering schedule loop. Checking for changes every 20 seconds.")
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(20)
