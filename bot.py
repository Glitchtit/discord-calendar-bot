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
print(f"[DEBUG] DISCORD_WEBHOOK_URL: {DISCORD_WEBHOOK_URL}")
SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
print(f"[DEBUG] GOOGLE_APPLICATION_CREDENTIALS: {SERVICE_ACCOUNT_FILE}")

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)

EVENTS_FILE = "/app/data/events.json"

def get_accessible_calendars():
    result = service.calendarList().list().execute()
    calendars = {}

    for cal in result.get("items", []):
        cal_id = cal["id"]
        cal_name = cal.get("summaryOverride") or cal.get("summary")
        # Assign a hash-based color (or pick from a predefined list)
        color = hash(cal_id) % 0xFFFFFF  # random color from ID

        calendars[cal_id] = {
            "name": cal_name,
            "color": color
        }
        print(f"[DEBUG] Found calendar: {cal_name} ({cal_id})")

    return calendars


# Define multiple calendars with name and embed color
CALENDARS = get_accessible_calendars()


# 1. LOADING / SAVING EVENTS

def load_previous_events():
    if os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                pass
    return {}

def save_current_events_for_key(key, events):
    all_data = load_previous_events()
    all_data[key] = events
    with open(EVENTS_FILE, "w") as f:
        json.dump(all_data, f)

# 2. DISCORD EMBEDS + FORMATTING

def post_embed_to_discord(title: str, description: str, color: int = 5814783):
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
    start = event["start"].get("dateTime", event["start"].get("date"))
    end   = event["end"].get("dateTime", event["end"].get("date"))
    title = event.get("summary", "No Title")
    location = event.get("location", "")

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

# 3. FETCH EVENTS

def get_events_for_day(date_obj, calendar_id):
    start_utc = date_obj.isoformat() + "T00:00:00Z"
    end_utc   = date_obj.isoformat() + "T23:59:59Z"

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

def get_events_for_week(monday_date, calendar_id):
    start_utc = monday_date.isoformat() + "T00:00:00Z"
    end_of_week = monday_date + timedelta(days=6)
    end_utc   = end_of_week.isoformat() + "T23:59:59Z"

    result = service.events().list(
        calendarId=calendar_id,
        timeMin=start_utc,
        timeMax=end_utc,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

# 4. DETECT CHANGES

def extract_comparable_fields(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
    summary = event.get("summary", "")
    location = event.get("location", "")
    description = event.get("description", "")
    return (start, end, summary, location, description)

def detect_changes(old_events, new_events):
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    old_ids = set(old_dict.keys())
    new_ids = set(new_dict.keys())

    for eid in new_ids - old_ids:
        changes.append(f"Event added: {format_event(new_dict[eid])}")

    for eid in old_ids - new_ids:
        changes.append(f"Event removed: {format_event(old_dict[eid])}")

    for eid in old_ids & new_ids:
        if extract_comparable_fields(old_dict[eid]) != extract_comparable_fields(new_dict[eid]):
            changes.append(
                f"Event changed:\nOLD: {format_event(old_dict[eid])}\nNEW: {format_event(new_dict[eid])}"
            )
    return changes

# 5. POSTING HAPPENINGS

def post_todays_happenings():
    today = datetime.now(tz=tz.tzlocal()).date()

    for calendar_id, meta in CALENDARS.items():
        calendar_name = meta["name"]
        color = meta["color"]
        key = f"DAILY_{calendar_id}_{today}"

        all_data = load_previous_events()
        old_events = all_data.get(key, [])
        new_events = get_events_for_day(today, calendar_id)

        changes = detect_changes(old_events, new_events)
        if changes:
            post_embed_to_discord(f"Changes Detected for: {calendar_name}", "\n".join(changes), color)

        if new_events:
            lines = [format_event(e) for e in new_events]
            post_embed_to_discord(f"Today’s Happenings for: {calendar_name}", "\n".join(lines), color)
        else:
            post_embed_to_discord(f"Today’s Happenings for: {calendar_name}", "No events scheduled for today.", color)

        save_current_events_for_key(key, new_events)

def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())

    for calendar_id, meta in CALENDARS.items():
        calendar_name = meta["name"]
        color = meta["color"]
        key = f"WEEK_{calendar_id}_{monday}"

        all_data = load_previous_events()
        old_events = all_data.get(key, [])
        new_events = get_events_for_week(monday, calendar_id)

        changes = detect_changes(old_events, new_events)
        if changes:
            post_embed_to_discord(f"Changes Detected for: {calendar_name}", "\n".join(changes), color)

        if new_events:
            lines = [format_event(e) for e in new_events]
            post_embed_to_discord(f"This Week’s Happenings for: {calendar_name}", "\n".join(lines), color)
        else:
            post_embed_to_discord(f"This Week’s Happenings for: {calendar_name}", "No events scheduled for this week.", color)

        save_current_events_for_key(key, new_events)

def check_for_changes():
    print("[DEBUG] check_for_changes() called.")
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())

    for calendar_id, meta in CALENDARS.items():
        calendar_name = meta["name"]
        color = meta["color"]

        daily_key = f"DAILY_{calendar_id}_{today}"
        week_key = f"WEEK_{calendar_id}_{monday}"

        all_data = load_previous_events()
        old_daily = all_data.get(daily_key, [])
        old_week = all_data.get(week_key, [])

        new_daily = get_events_for_day(today, calendar_id)
        new_week = get_events_for_week(monday, calendar_id)

        daily_changes = detect_changes(old_daily, new_daily)
        weekly_changes = detect_changes(old_week, new_week)

        if daily_changes:
            post_embed_to_discord(f"Changes Detected for: {calendar_name} (Today)", "\n".join(daily_changes), color)
        if weekly_changes:
            post_embed_to_discord(f"Changes Detected for: {calendar_name} (Week)", "\n".join(weekly_changes), color)

        save_current_events_for_key(daily_key, new_daily)
        save_current_events_for_key(week_key, new_week)

    print("[DEBUG] check_for_changes() finished.")

# 6. SCHEDULE

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
