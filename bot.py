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

    # Optionally include location in parentheses
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
# 4. DETECT CHANGES
#
def detect_changes(old_events, new_events):
    """
    Compare the old vs. new event lists based on their IDs.
    Return a list of lines describing added/removed events.
    """
    changes = []
    old_ids = {e["id"] for e in old_events}
    new_ids = {e["id"] for e in new_events}

    added   = [e for e in new_events if e["id"] not in old_ids]
    removed = [e for e in old_events if e["id"] not in new_ids]

    for ev in added:
        changes.append(f"Event added: {format_event(ev)}")
    for ev in removed:
        changes.append(f"Event removed: {format_event(ev)}")

    return changes

def post_changes_embed(changes):
    """
    If there are changes, send them in a nicely embedded message.
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
    Posts today's events in an embed. Also checks for changes
    (since we might not have posted them if no changes triggered).
    """
    today = datetime.now(tz=tz.tzlocal()).date()
    daily_key = f"DAILY_{today}"

    all_data = load_previous_events()
    old_daily_events = all_data.get(daily_key, [])

    # Fetch today's events
    today_events = get_events_for_day(today)

    # Check & post changes found
    changes = detect_changes(old_daily_events, today_events)
    post_changes_embed(changes)

    # Then post daily summary
    if today_events:
        lines = [format_event(e) for e in today_events]
        description = "\n".join(lines)
        post_embed_to_discord("Today’s Happenings", description)
    else:
        post_embed_to_discord("Today’s Happenings", "No events scheduled for today.")

    # Save
    save_current_events_for_key(daily_key, today_events)

#
# 6. WEEKLY SUMMARY (SCHEDULED)
#
def post_weeks_happenings():
    """
    Runs once a week (Monday 09:00).
    Posts the entire Monday–Sunday events in an embed, plus any changes.
    """
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    week_key = f"WEEK_{monday}"

    all_data = load_previous_events()
    old_week_events = all_data.get(week_key, [])

    # Fetch week events
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

    # Save
    save_current_events_for_key(week_key, week_events)

#
# 7. REAL-TIME CHANGES EVERY MINUTE
#
def check_for_changes():
    """
    Check daily and weekly sets each minute, but only post changes if there are any.
    No full "today's happenings" or "this week's happenings" summaries here.
    """
    print("[DEBUG] check_for_changes() called.")

    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())

    #
    # 1) Check for changes in today's events
    #
    daily_key = f"DAILY_{today}"
    all_data = load_previous_events()
    old_daily_events = all_data.get(daily_key, [])

    today_events = get_events_for_day(today)
    daily_changes = detect_changes(old_daily_events, today_events)

    if daily_changes:
        # Only post to Discord if there's something new or removed
        post_changes_embed(daily_changes)

    # Update the JSON so we don't repeat the same changes next loop
    save_current_events_for_key(daily_key, today_events)

    #
    # 2) Check for changes in this week's events
    #
    week_key = f"WEEK_{monday}"
    # Reload the data (in case we just wrote daily data)
    all_data = load_previous_events()
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

    print("[DEBUG] Entering schedule loop. Checking for changes every 60 seconds.")
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(60)
