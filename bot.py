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
        "DAILY_2025-03-28": [ ...list of events... ],
        "WEEK_2025-03-25":  [ ...list of events... ]
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
# 2. DISCORD + FORMATTING
#
def post_to_discord(message: str, embed: dict = None):
    """
    Sends a message to the Discord channel via webhook.
    """
    print("[DEBUG] post_to_discord() called. Sending message to Discord...")
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] DISCORD_WEBHOOK_URL is not set. Cannot send message.")
        return

    payload = {"content": message}
    if embed:
        payload["embeds"] = [embed]

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Failed to send message. Status: {resp.status_code} - {resp.text}")
    else:
        print("[DEBUG] Message sent to Discord successfully.")

def create_embed(title: str, description: str) -> dict:
    """
    Create an embed dictionary for Discord messages.
    """
    return {
        "title": title,
        "description": description,
        "color": 5814783  # A nice blue color
    }

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

    # If a location is specified, include it in the output
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

def extract_comparable_fields(event):
    """
    Return the key pieces of data we care about for detecting changes
    (start time, end time, summary). If any of these differ,
    we consider the event 'changed'.
    """
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)


def detect_changes(old_events, new_events):
    """
    Compare old_events vs. new_events:
      - Added: ID in new but not in old
      - Removed: ID in old but not in new
      - Changed: ID in both, but start/end/summary have changed
    Returns a list of "Event added/removed/changed..." lines.
    """
    changes = []

    # Convert old_events, new_events to dicts by ID for easy lookup
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}

    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    # 1) Removed
    removed_ids = old_ids - new_ids
    for rid in removed_ids:
        changes.append(f"Event removed: {format_event(old_dict[rid])}")

    # 2) Added
    added_ids = new_ids - old_ids
    for aid in added_ids:
        changes.append(f"Event added: {format_event(new_dict[aid])}")

    # 3) Potentially Changed
    common_ids = old_ids & new_ids
    for cid in common_ids:
        old_fields = extract_comparable_fields(old_dict[cid])
        new_fields = extract_comparable_fields(new_dict[cid])
        # If the relevant fields differ, we consider it "changed"
        if old_fields != new_fields:
            changes.append(
                f"Event changed:\n"
                f"OLD: {format_event(old_dict[cid])}\n"
                f"NEW: {format_event(new_dict[cid])}"
            )

    return changes


def post_changes_to_discord(changes):
    """
    Post detected changes to Discord.
    """
    if changes:
        description = "\n".join(changes)
        embed = create_embed("Changes Detected", description)
        post_to_discord("", embed)
        print("[DEBUG] Changes detected and posted to Discord.")
    else:
        print("[DEBUG] No changes detected.")

#
# 5. DAILY LOGIC
#
def post_todays_happenings():
    """
    Retrieve today's events and post them to Discord.
    """
    print("[DEBUG] post_todays_happenings() called. Attempting to fetch today's events.")
    today = datetime.now(tz=tz.tzlocal()).date()
    events = get_events_for_day(today)
    previous_events = load_previous_events().get(f"DAILY_{today}", [])

    changes = detect_changes(previous_events, events)
    post_changes_to_discord(changes)

    if not events:
        message = "No events scheduled for today."
        embed = create_embed("Today’s Happenings", message)
        post_to_discord("", embed)
    else:
        lines = [format_event(e) for e in events]
        description = "\n".join(lines)
        embed = create_embed("Today’s Happenings", description)
        post_to_discord("", embed)

    save_current_events_for_key(f"DAILY_{today}", events)
    print("[DEBUG] post_todays_happenings() finished. Check Discord for today's post.")

#
# 6. WEEKLY LOGIC (including single-day events)
#
def post_weeks_happenings():
    """
    Retrieve events for Monday–Sunday of the current week and post them.
    """
    print("[DEBUG] post_weeks_happenings() called. Attempting to fetch this week's events.")
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())  # 0=Monday, 6=Sunday
    events = get_events_for_week(monday)
    previous_events = load_previous_events().get(f"WEEK_{monday}", [])

    changes = detect_changes(previous_events, events)
    post_changes_to_discord(changes)

    if not events:
        message = "No events scheduled for this week."
        embed = create_embed("This Week’s Happenings", message)
        post_to_discord("", embed)
    else:
        lines = [format_event(e) for e in events]
        description = "\n".join(lines)
        embed = create_embed("This Week’s Happenings", description)
        post_to_discord("", embed)

    save_current_events_for_key(f"WEEK_{monday}", events)
    print("[DEBUG] post_weeks_happenings() finished. Check Discord for weekly post.")

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

    #if daily_changes:
        # Only post to Discord if there's something new or removed
        #post_changes_to_discord(daily_changes)

    # Update the JSON so we don't repeat the same changes next loop
    save_current_events_for_key(daily_key, today_events)

    #
    # 2) Check for changes in this week's events
    #
    week_key = f"WEEK_{monday}"
    # Reload the data in case we just wrote daily data
    all_data = load_previous_events()
    old_week_events = all_data.get(week_key, [])

    week_events = get_events_for_week(monday)
    weekly_changes = detect_changes(old_week_events, week_events)

    if weekly_changes:
        post_changes_to_discord(weekly_changes)

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

    print("[DEBUG] Entering schedule loop. Checking for changes every 30 seconds.")
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(30)
