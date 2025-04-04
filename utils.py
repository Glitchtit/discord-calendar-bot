"""
utils.py: General utilities to support event formatting, date/time handling, etc.
"""

from datetime import date, datetime, timedelta
from typing import Dict, Any

from events import GROUPED_CALENDARS
from zoneinfo import ZoneInfo
from log import logger

# ╔════════════════════════════════════════════════════════════════════╗
# 📆 Date Utilities
# ╚════════════════════════════════════════════════════════════════════╝

def get_today() -> date:
    """
    Retrieves the current local date (no time component).

    Returns:
        A date object representing today's date in local time.
    """
    today = datetime.now().date()
    logger.debug(f"[utils.py] get_today() -> {today}")
    return today

def get_monday_of_week(ref: date = None) -> date:
    """
    Given a reference date, returns the Monday of that week. If no ref is provided,
    uses today's date.

    Args:
        ref: The reference date (default: today's date).

    Returns:
        The date object corresponding to Monday of the same week as ref.
    """
    if ref is None:
        ref = get_today()
    monday = ref - timedelta(days=ref.weekday())
    logger.debug(f"[utils.py] get_monday_of_week({ref}) -> {monday}")
    return monday

def is_in_current_week(event_start: str) -> bool:
    """
    Checks if an event's start date/time falls in the current week
    (Monday–Sunday) based on local time.

    Args:
        event_start: An ISO 8601 datetime string, potentially with 'Z' for UTC.

    Returns:
        True if the event's start is between Monday of the current local week
        and Sunday of that same week, else False.
    """
    try:
        dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
        today = get_today()
        monday = get_monday_of_week(today)
        in_week = monday <= dt.date() <= monday + timedelta(days=6)
        logger.debug(f"[utils.py] is_in_current_week({event_start}) -> {in_week}")
        return in_week
    except ValueError as e:
        logger.warning(f"[utils.py] Failed to parse date '{event_start}': {e}")
        return False

def resolve_tz(tzid: str) -> ZoneInfo:
    """
    Attempts to resolve a TZID string to a valid zone. Defaults to UTC if invalid.

    Args:
        tzid: Time zone identifier string (e.g., "America/New_York").

    Returns:
        A ZoneInfo object representing the resolved time zone.
    """
    try:
        return ZoneInfo(tzid)
    except Exception:
        logger.warning(f"[utils.py] Unknown TZID: {tzid}, defaulting to UTC.")
        return ZoneInfo("UTC")


# ╔════════════════════════════════════════════════════════════════════╗
# ✨ Event Formatting
# ╚════════════════════════════════════════════════════════════════════╝

def format_event(event: Dict[str, Any]) -> str:
    """
    Formats an event dictionary into a user-facing string for Discord embeds.

    Args:
        event: A dictionary containing event fields such as 'summary', 'location',
               'start', 'end', and 'allDay'.

    Returns:
        A formatted string describing the event's title, time (or all-day),
        and location if available.
    """
    summary = event.get("summary", "Untitled")
    location = event.get("location", "")
    is_all_day = event.get("allDay", False)

    start = event["start"].get("dateTime", event["start"].get("date"))
    end = event["end"].get("dateTime", event["end"].get("date"))

    time_str = "📌 All day"
    # If not all-day, extract time portion (HH:MM)
    if not is_all_day and "T" in start:
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%H:%M")
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00")).strftime("%H:%M")
        time_str = f"🕒 {start_time}–{end_time}"

    loc_str = f"📍 {location}" if location else ""
    formatted = f"**{summary}**\n{time_str} {loc_str}".strip()
    logger.debug(f"[utils.py] format_event(...) -> {formatted}")
    return formatted


# ╔════════════════════════════════════════════════════════════════════╗
# 🔤 Tag Resolution
# ╚════════════════════════════════════════════════════════════════════╝

def resolve_input_to_tags(value: str) -> list[str]:
    """
    Converts a user-provided tag-like string to a list of valid tags. If
    the user input is something like '*', 'ALL', or 'BOTH', returns all known tags.

    Args:
        value: The user-provided tag string.

    Returns:
        A list of uppercase tags that exist in GROUPED_CALENDARS.
    """
    value = value.strip().upper()
    if value in ("*", "ALL", "BOTH"):
        tags = list(GROUPED_CALENDARS.keys())
        logger.debug(f"[utils.py] resolve_input_to_tags('{value}') -> ALL TAGS: {tags}")
        return tags
    if value in GROUPED_CALENDARS:
        logger.debug(f"[utils.py] resolve_input_to_tags('{value}') -> SINGLE TAG: {value}")
        return [value]

    logger.debug(f"[utils.py] resolve_input_to_tags('{value}') -> NONE")
    return []
