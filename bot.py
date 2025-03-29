import schedule
import time
from datetime import datetime, timedelta
from dateutil import tz
from events import (
    GROUPED_CALENDARS,
    get_events,
    save_current_events_for_key,
    load_previous_events,
    get_color_for_tag,
    get_name_for_tag
)
from ai import post_greeting_to_discord
import requests
import os
import json

def format_event(event) -> str:
    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))
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
    return f"- {title} ({start_str} to {end_str}" + (f", at {location})" if location else ")")

def post_embed_to_discord(title: str, description: str, color: int = 5814783):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
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
    resp = requests.post(webhook, json=payload)
    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord post successful.")

def post_todays_happenings():
    today = datetime.now(tz=tz.tzlocal()).date()
    weekday_name = today.strftime("%A")
    all_events_for_greeting = []
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, today, today)
        if all_events:
            all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
            lines = [format_event(e) for e in all_events]
            post_embed_to_discord(
                f"Today’s Happenings – {weekday_name} for {get_name_for_tag(tag)}",
                "\n".join(lines),
                get_color_for_tag(tag)
            )
            all_events_for_greeting += all_events
    post_greeting_to_discord(all_events_for_greeting)

def post_weeks_happenings():
    now = datetime.now(tz=tz.tzlocal()).date()
    monday = now - timedelta(days=now.weekday())
    end = monday + timedelta(days=6)
    for tag, calendars in GROUPED_CALENDARS.items():
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, monday, end)
        if not all_events:
            continue
        events_by_day = {}
        for e in all_events:
            start_str = e["start"].get("dateTime", e["start"].get("date"))
            dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if "T" in start_str else datetime.fromisoformat(start_str)
            day = dt.date()
            events_by_day.setdefault(day, []).append(e)
        lines = []
        for i in range(7):
            day = monday + timedelta(days=i)
            if day in events_by_day:
                lines.append(f"**{day.strftime('%A')}**")
                day_events = sorted(events_by_day[day], key=lambda e: e["start"].get("dateTime", e["start"].get("date")))
                lines.extend(format_event(e) for e in day_events)
                lines.append("")
        post_embed_to_discord(
            f"This Week’s Happenings for {get_name_for_tag(tag)}",
            "\n".join(lines),
            get_color_for_tag(tag)
        )

def extract_comparable_fields(event):
    return (
        event["start"].get("dateTime", event["start"].get("date")),
        event["end"].get("dateTime", event["end"].get("date")),
        event.get("summary", ""),
        event.get("location", ""),
        event.get("description", "")
    )

def detect_changes(old_events, new_events):
    changes = []
    old_dict = {e["id"]: e for e in old_events}
    new_dict = {e["id"]: e for e in new_events}
    for eid in new_dict.keys() - old_dict.keys():
        changes.append(f"Event added: {format_event(new_dict[eid])}")
    for eid in old_dict.keys() - new_dict.keys():
        changes.append(f"Event removed: {format_event(old_dict[eid])}")
    for eid in new_dict.keys() & old_dict.keys():
        if extract_comparable_fields(new_dict[eid]) != extract_comparable_fields(old_dict[eid]):
            changes.append(
                f"Event changed:\nOLD: {format_event(old_dict[eid])}\nNEW: {format_event(new_dict[eid])}"
            )
    return changes

def check_for_changes():
    today = datetime.now(tz=tz.tzlocal()).date()
    monday = today - timedelta(days=today.weekday())
    end = monday + timedelta(days=6)
    now = datetime.now(tz=tz.tzlocal())
    scheduled_time = now.replace(hour=8, minute=1, second=0, microsecond=0)
    delta = abs((now - scheduled_time).total_seconds())
    for tag, calendars in GROUPED_CALENDARS.items():
        key = f"WEEK_{tag}_{monday}"
        all_previous = load_previous_events()
        is_first_time = key not in all_previous
        old_events = all_previous.get(key, [])
        new_events = []
        for meta in calendars:
            new_events += get_events(meta, monday, end)
        changes = detect_changes(old_events, new_events)
        if is_first_time:
            print(f"[DEBUG] Initial event snapshot for {tag} — storing without posting.")
            save_current_events_for_key(key, new_events)
        elif changes and delta > 180:
            post_embed_to_discord(
                f"Changes Detected – For {get_name_for_tag(tag)}",
                "\n".join(changes),
                get_color_for_tag(tag)
            )
            save_current_events_for_key(key, new_events)
        elif changes:
            print(f"[DEBUG] Suppressed weekly change post for {tag} due to timing (±3 min).")
            save_current_events_for_key(key, new_events)

def fetch_and_store_future_events():
    today = datetime.now(tz=tz.tzlocal()).date()
    end = today + timedelta(days=180)
    for tag, calendars in GROUPED_CALENDARS.items():
        key = f"FUTURE_{tag}_{today}"
        all_events = []
        for meta in calendars:
            all_events += get_events(meta, today, end)
        if all_events:
            save_current_events_for_key(key, all_events)
        print(f"[DEBUG] Stored {len(all_events)} events for {get_name_for_tag(tag)} ({tag}) from {today} to {end}")

if __name__ == "__main__":
    print("[DEBUG] Bot started. Fetching 6 months of future events now.")
    fetch_and_store_future_events()
    check_for_changes()
    print("[DEBUG] Posting weekly + daily events now.")
    post_weeks_happenings()
    post_todays_happenings()
    print("[DEBUG] Entering schedule loop.")
    schedule.every().day.at("08:01").do(post_todays_happenings)
    schedule.every().monday.at("08:00").do(post_weeks_happenings)
    while True:
        schedule.run_pending()
        check_for_changes()
        time.sleep(20)
