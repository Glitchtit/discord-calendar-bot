# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        CALENDAR BOT UTILITY FUNCTIONS                    ║
# ║    Shared helpers for date, event, tag, and config operations            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from datetime import datetime, timedelta, date
from dateutil import tz
from utils.logging import logger
import functools
import re
import os
from collections import defaultdict
import json
from typing import Dict, Any
from threading import Lock

_timezone_cache = None
_date_str_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_datetime_str_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TIMEZONE UTILITIES                                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_local_timezone ---
# Retrieves the system's local timezone using dateutil.tz.tzlocal().
# Caches the result to avoid repeated lookups.
# Falls back to UTC if the local timezone cannot be determined.
# Returns: The local timezone object (or tz.UTC on failure).
def get_local_timezone():
    global _timezone_cache
    if (_timezone_cache is not None):
        return _timezone_cache
    try:
        _timezone_cache = tz.tzlocal()
        return _timezone_cache
    except Exception as e:
        logger.warning(f"Failed to get local timezone: {e}. Falling back to UTC.")
        _timezone_cache = tz.UTC
        return _timezone_cache

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ DATE UTILITIES                                                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_today ---
# Gets the current date based on the local timezone.
# Uses UTC as a fallback if the local timezone fails.
# Returns: A date object representing today.
def get_today() -> date:
    try:
        return datetime.now(tz=get_local_timezone()).date()
    except Exception as e:
        logger.exception(f"Error getting today's date: {e}. Using UTC.")
        return datetime.now(tz=tz.UTC).date()

# --- get_monday_of_week ---
# Calculates the date of the Monday for the week containing the given `day`.
# If `day` is None, it defaults to the current day.
# Handles both date and datetime objects as input.
# Args:
#     day: The date or datetime object to find the Monday for (defaults to today).
# Returns: A date object representing the Monday of the week.
def get_monday_of_week(day: date = None) -> date:
    if day is None:
        day = get_today()
    if isinstance(day, datetime):
        day = day.date()
    try:
        return day - timedelta(days=day.weekday())
    except Exception as e:
        logger.exception(f"Error calculating Monday of week for {day}: {e}")
        today = get_today()
        return today - timedelta(days=today.weekday())

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EVENT FORMATTING                                                          ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- emoji_for_event ---
# Selects an appropriate emoji based on keywords in the event title.
# Used to add visual cues to event listings.
# Args:
#     title: The event title string.
# Returns: An emoji string (defaults to "•").
def emoji_for_event(title: str) -> str:
    if not title or not isinstance(title, str):
        return "•"
    try:
        title = title.lower()
        if "class" in title or "lecture" in title or "em" in title or "ia" in title:
            return "📚"
        if "meeting" in title:
            return "📞"
        if "lunch" in title:
            return "🥪"
        if "dinner" in title or "banquet" in title:
            return "🍽️"
        if "party" in title:
            return "🎉"
        if "exam" in title or "test" in title:
            return "📝"
        if "appointment" in title:
            return "📅"
        return "•"
    except Exception as e:
        logger.exception(f"Error determining emoji for title '{title}': {e}")
        return "•"

# --- parse_date_string ---
# Parses various ISO 8601 date/datetime string formats into datetime objects.
# Handles date-only strings, UTC ('Z') notation, and timezone offsets.
# Assumes UTC if no timezone is present and converts to the default_timezone.
# Args:
#     date_str: The date/datetime string to parse.
#     default_timezone: The timezone to assume/convert to if none is specified (defaults to local).
# Returns: A datetime object or None if parsing fails.
def parse_date_string(date_str: str, default_timezone=None):
    if not date_str:
        logger.warning("Empty date string provided")
        return None
    if default_timezone is None:
        default_timezone = get_local_timezone()
    try:
        if _date_str_pattern.match(date_str):
            return datetime.fromisoformat(date_str)
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        if '+' not in date_str and '-' not in date_str[-6:]:
            dt = datetime.fromisoformat(date_str)
            dt = dt.replace(tzinfo=tz.UTC)
            return dt.astimezone(default_timezone)
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date string '{date_str}': {e}")
        return None

# --- format_event ---
# Formats a single event dictionary into a readable string for Discord messages.
# Includes emoji, title (truncated), time range, and location (optional).
# Handles all-day events and events with specific start/end times.
# Args:
#     event: The event dictionary (usually from Google Calendar API).
# Returns: A formatted string representation of the event.
def format_event(event: dict) -> str:
    try:
        if not event or not isinstance(event, dict):
            logger.warning(f"Invalid event data: {event}")
            return "⚠️ **Invalid event data**"
        start_data = event.get("start", {})
        end_data = event.get("end", {})
        if not isinstance(start_data, dict) or not isinstance(end_data, dict):
            logger.warning(f"Invalid start/end data format in event: {event}")
            return "⚠️ **Invalid event format**"
        start = start_data.get("dateTime", start_data.get("date", ""))
        end = end_data.get("dateTime", end_data.get("date", ""))
        title = event.get("summary", "Untitled")
        if isinstance(title, str):
            if len(title) > 50:
                title = title[:47] + "..."
            title = title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
        else:
            title = "Untitled"
        location = event.get("location", "")
        if isinstance(location, str):
            location = location.replace("*", "\\*").replace("_", "\\_")
        else:
            location = ""
        emoji = emoji_for_event(title)
        local_timezone = get_local_timezone()
        start_str = "All Day"
        if start and "T" in start:
            start_dt = parse_date_string(start, local_timezone)
            if start_dt:
                start_str = start_dt.strftime("%H:%M")
        end_str = ""
        if end and "T" in end:
            end_dt = parse_date_string(end, local_timezone)
            if end_dt:
                end_str = end_dt.strftime("%H:%M")
        time_range = f"{start_str}–{end_str}" if end_str else start_str
        location_str = f" *({location})*" if location else ""
        return f"{emoji} **{title}** `{time_range}`{location_str}"
    except Exception as e:
        logger.exception(f"Error formatting event: {e}")
        return "⚠️ **Error formatting event**"

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TAG & INPUT RESOLUTION                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- is_in_current_week ---
# Checks if an event's start date falls within the week of the reference date.
# Args:
#     event: The event dictionary.
#     reference: The reference date to define the week (defaults to today).
# Returns: True if the event is in the current week, False otherwise.
def is_in_current_week(event: dict, reference: date = None) -> bool:
    try:
        if not event or not isinstance(event, dict):
            return False
        reference = reference or get_today()
        monday = get_monday_of_week(reference)
        week_range = {monday + timedelta(days=i) for i in range(7)}
        start_data = event.get("start", {})
        if not isinstance(start_data, dict):
            return False
        start_str = start_data.get("dateTime", start_data.get("date", ""))
        if not start_str:
            return False
        dt = parse_date_string(start_str)
        if not dt:
            return False
        return dt.date() in week_range
    except Exception as e:
        logger.exception(f"Error checking if event is in current week: {e}")
        return False

# --- resolve_input_to_tags ---
# Attempts to match user input text to known calendar tag IDs or names.
# Used for commands where users specify which calendar(s) to act upon.
# Args:
#     input_text: The text provided by the user.
#     tag_names: A dictionary mapping tag IDs to their display names.
#     grouped_calendars: A dictionary mapping tag IDs to their calendar configurations.
# Returns: A list of matching tag IDs. Returns all tag IDs if input is empty.
def resolve_input_to_tags(input_text: str, tag_names: dict, grouped_calendars: dict) -> list:
    if not input_text or not input_text.strip():
        return list(grouped_calendars.keys())
    input_lower = input_text.lower().strip()
    matches = []
    if input_text in grouped_calendars:
        return [input_text]
    for tag_id, name in tag_names.items():
        if input_lower == name.lower():
            return [tag_id]
        if input_lower in name.lower():
            matches.append(tag_id)
    if matches:
        return matches
    for tag_id in grouped_calendars:
        if input_lower in str(tag_id).lower():
            matches.append(tag_id)
    return matches

# --- validate_env_vars ---
# Checks if all specified environment variables are set.
# Raises an EnvironmentError if any required variable is missing.
# Args:
#     required_vars: A list of environment variable names to check.
def validate_env_vars(required_vars):
    for var in required_vars:
        if not os.getenv(var):
            logger.error(f"Environment variable {var} is not set. Please configure it.")
            raise EnvironmentError(f"Missing required environment variable: {var}")

# --- format_message_lines ---
# Formats a collection of events grouped by day (or calendar for daily view)
# into a list of strings suitable for sending as a Discord message.
# Handles headers for daily, weekly, or single-day views.
# Args:
#     user_id: The Discord user ID to mention in the header.
#     events_by_day: A dictionary mapping dates (or calendar names) to lists of events.
#     start_date: The reference date (e.g., today for daily, Monday for weekly).
# Returns: A list of strings, each representing a line in the final message.
def format_message_lines(user_id, events_by_day, start_date):
    is_daily = isinstance(next(iter(events_by_day.keys()), None), str)
    is_single_day = len(events_by_day) == 1 and isinstance(next(iter(events_by_day.keys()), None), date)
    user_mention = f"<@{user_id}>"
    if is_daily:
        header = f"📅 **Today's Events for {user_mention} ({start_date.strftime('%A, %B %d')})**\n"
    elif is_single_day:
        day = next(iter(events_by_day.keys()))
        header = f"📅 **Events for {user_mention} on {day.strftime('%A, %B %d')}**\n"
    else:
        header = f"📆 **Weekly Events for {user_mention} — Week of {start_date.strftime('%B %d')}**\n"
    message_lines = [header]
    if is_daily:
        for calendar_name, events in sorted(events_by_day.items()):
            if events:
                message_lines.append(f"📁 **{calendar_name}**")
                for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                    message_lines.append(format_event(e))
                message_lines.append("")
    else:
        for day, events in sorted(events_by_day.items()):
            message_lines.append(f"📆 **{day.strftime('%A, %B %d')}**")
            if not events:
                message_lines.append("*No events scheduled*\n")
            else:
                for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                    message_lines.append(format_event(e))
                message_lines.append("")
    return message_lines

_load_lock = Lock()

# --- load_server_config ---
# Loads the JSON configuration file for a specific server ID.
# Uses a lock to prevent race conditions during file access.
# Returns an empty config structure if the file doesn't exist or is invalid.
# Args:
#     server_id: The Discord server (guild) ID.
# Returns: A dictionary containing the server's configuration.
def load_server_config(server_id: int) -> Dict[str, Any]:
    config_path = f"./data/servers/{server_id}.json"
    try:
        with _load_lock:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as file:
                    return json.load(file)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in config file for server {server_id}")
    except Exception as e:
        logger.exception(f"Error loading server config for server {server_id}: {e}")
    return {"calendars": [], "user_mappings": {}}

# --- add_calendar ---
# Adds a new calendar configuration to a server's config file.
# Prevents adding duplicates based on calendar ID.
# Args:
#     server_id: The Discord server (guild) ID.
#     calendar_data: A dictionary containing the new calendar's details.
# Returns: True if the calendar was added successfully, False otherwise.
def add_calendar(server_id: int, calendar_data: dict) -> bool:
    try:
        config = load_server_config(server_id)
        calendars = config.get("calendars", [])
        if any(calendar.get("id") == calendar_data.get("id") for calendar in calendars):
            logger.warning(f"Calendar with ID {calendar_data.get('id')} already exists for server {server_id}.")
            return False
        calendars.append(calendar_data)
        config["calendars"] = calendars
        with open(f"./data/servers/{server_id}.json", "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)
        return True
    except Exception as e:
        logger.exception(f"Error adding calendar {calendar_data.get('id')} for server {server_id}: {e}")
        return False

# --- remove_calendar ---
# Removes a calendar configuration from a server's config file based on its ID.
# Args:
#     server_id: The Discord server (guild) ID.
#     calendar_id: The ID of the calendar to remove.
# Returns: True if the calendar was found and removed, False otherwise.
def remove_calendar(server_id: int, calendar_id: str) -> bool:
    try:
        config = load_server_config(server_id)
        calendars = config.get("calendars", [])
        for calendar in calendars:
            if calendar.get("id") == calendar_id:
                calendars.remove(calendar)
                with open(f"./data/servers/{server_id}.json", "w", encoding="utf-8") as file:
                    json.dump(config, file, indent=4)
                return True
        return False
    except Exception as e:
        logger.exception(f"Error removing calendar {calendar_id} for server {server_id}: {e}")
        return False
