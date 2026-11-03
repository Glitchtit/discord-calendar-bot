from datetime import datetime, timedelta, date
from dateutil import tz
from log import logger  # Import logger from log.py
import functools
import re

# Cache for expensive operations
_timezone_cache = None
_date_str_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_datetime_str_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}')

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🌐 get_local_timezone                                              ║
# ║ Gets local timezone with fallback to UTC if detection fails        ║
# ╚════════════════════════════════════════════════════════════════════╝
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


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 get_today                                                       ║
# ║ Returns the current date in the local timezone                    ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_today() -> date:
    try:
        return datetime.now(tz=get_local_timezone()).date()
    except Exception as e:
        logger.exception(f"Error getting today's date: {e}. Using UTC.")
        # Fallback to UTC in case of error
        return datetime.now(tz=tz.UTC).date()


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📆 get_monday_of_week                                              ║
# ║ Returns the Monday of the given date's week                        ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_monday_of_week(day: date = None) -> date:
    if day is None:
        day = get_today()
    
    # Ensure we have a date object
    if isinstance(day, datetime):
        day = day.date()
    
    try:
        return day - timedelta(days=day.weekday())
    except Exception as e:
        logger.exception(f"Error calculating Monday of week for {day}: {e}")
        # Return today's Monday as fallback
        today = get_today()
        return today - timedelta(days=today.weekday())


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🕒 parse_date_string                                               ║
# ║ Safely parses ISO date/datetime strings with fallbacks             ║
# ╚════════════════════════════════════════════════════════════════════╝
def parse_date_string(date_str: str, default_timezone=None):
    """Parse a date string safely, handling different formats and edge cases."""
    if not date_str:
        logger.warning("Empty date string provided")
        return None
        
    if default_timezone is None:
        default_timezone = get_local_timezone()
    
    try:
        # Handle date-only format (YYYY-MM-DD) - All day events
        if _date_str_pattern.match(date_str):
            # Create datetime at noon on the specified date in local timezone
            # Using noon avoids any potential date shifts during timezone conversions
            date_obj = datetime.fromisoformat(date_str).date()
            dt = datetime(date_obj.year, date_obj.month, date_obj.day, 12, 0, 0)
            return dt.replace(tzinfo=default_timezone)
            
        # Handle Z (UTC) timezone indicator
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
            
        # Handle missing timezone information
        if '+' not in date_str and '-' not in date_str[-6:]:
            # If no timezone info, assume UTC then convert to local
            dt = datetime.fromisoformat(date_str)
            dt = dt.replace(tzinfo=tz.UTC)
            return dt.astimezone(default_timezone)
            
        # Normal case with timezone info: show it in the bot's timezone
        return datetime.fromisoformat(date_str).astimezone(default_timezone)
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date string '{date_str}': {e}")
        return None


def event_local_date(start_str: str):
    """Calendar date of an event start in the bot's timezone (None if unparseable)."""
    dt = parse_date_string(start_str)
    if dt is None:
        return None
    return dt.astimezone(get_local_timezone()).date() if "T" in start_str else dt.date()


def event_days(event: dict):
    """(first, last) local dates an event covers, or None. All-day end dates are
    exclusive, and a timed event ending exactly at midnight doesn't cover that day."""
    start_str = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
    end_str = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", "")) or start_str
    first = event_local_date(start_str) if start_str else None
    if first is None:
        return None
    if "T" in end_str:
        end = parse_date_string(end_str)
        last = (end - timedelta(microseconds=1)).date() if end else first
    else:
        last = date.fromisoformat(end_str) - timedelta(days=1)
    return first, max(first, last)


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_DDMM_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$")


def parse_agenda_date(text: str, today: date):
    """Parse /agenda input: today, tomorrow, DD.MM[.YYYY], [this|next] <weekday>,
    else dateparser (day-first). Returns a date or None."""
    import dateparser
    s = text.strip().lower()
    if s == "today":
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    m = _DDMM_RE.match(s)
    if m:
        day, month = int(m[1]), int(m[2])
        if m[3]:
            years = [int(m[3])]
        else:
            # No year: the nearest such date, so "2.1" asked in late December means next January
            years = [today.year - 1, today.year, today.year + 1]
        candidates = []
        for y in years:
            try:
                candidates.append(date(y, month, day))
            except ValueError:
                pass
        return min(candidates, key=lambda d: abs(d - today)) if candidates else None
    words = s.split()
    if words and words[-1] in _WEEKDAYS and len(words) <= 2 and (len(words) == 1 or words[0] in ("this", "next")):
        idx = _WEEKDAYS.index(words[-1])
        if words[0] == "next":  # that weekday in next week
            return get_monday_of_week(today) + timedelta(days=7 + idx)
        return today + timedelta(days=(idx - today.weekday()) % 7)  # upcoming, today included
    parsed = dateparser.parse(text, settings={"DATE_ORDER": "DMY", "PREFER_DATES_FROM": "future"})
    return parsed.date() if parsed else None


def shorten(text: str, limit: int) -> str:
    """Cut *text* to *limit* characters at a word boundary, ending with "…"."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" -–,.:;") + "…"


def escape_md(text: str) -> str:
    return re.sub(r"([*_`~|\\])", r"\\\1", text)


def event_when(event: dict, with_date: bool = False) -> str:
    """'08:30–11:00' or 'all day'; with_date: 'Fri 23.10 08:30–11:00' / 'Fri 23.10 · all day'."""
    start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
    end = event.get("end", {}).get("dateTime", event.get("end", {}).get("date", ""))
    if "T" not in start:
        days = event_days(event)
        if not with_date or not days:
            return "all day"
        first, last = days
        span = f"{first:%a %d.%m}" + (f"–{last:%a %d.%m}" if last != first else "")
        return f"{span} · all day"
    tz_ = get_local_timezone()
    s = parse_date_string(start, tz_)
    if not s:
        return ""
    e = parse_date_string(end, tz_) if "T" in end else None
    times = f"{s:%H:%M}" + (f"–{e:%H:%M}" if e else "")
    return f"{s:%a %d.%m} {times}" if with_date else times


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📝 format_event                                                    ║
# ║ One event as a Discord markdown line                               ║
# ╚════════════════════════════════════════════════════════════════════╝
def format_event(event: dict, with_date: bool = False) -> str:
    title = event.get("summary") if isinstance(event.get("summary"), str) else ""
    title = escape_md(shorten(title, 50)) or "Untitled"
    location = event.get("location") if isinstance(event.get("location"), str) else ""
    location_str = f" · *{escape_md(shorten(location, 40))}*" if location.strip() else ""
    return f"**{title}** `{event_when(event, with_date)}`{location_str}"


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 is_in_current_week                                              ║
# ║ Determines if an event occurs within the current week             ║
# ╚════════════════════════════════════════════════════════════════════╝
def is_in_current_week(event: dict, reference: date = None) -> bool:
    try:
        # Validate inputs
        if not event or not isinstance(event, dict):
            return False
            
        reference = reference or get_today()
        monday = get_monday_of_week(reference)

        start_data = event.get("start", {})
        if not isinstance(start_data, dict):
            return False
        start_str = start_data.get("dateTime", start_data.get("date", ""))
        if not start_str:
            return False

        # Same local-date rule as the agenda views
        day = event_local_date(start_str)
        return day is not None and monday <= day <= monday + timedelta(days=6)
    except Exception as e:
        logger.exception(f"Error checking if event is in current week: {e}")
        return False


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 resolve_input_to_tags                                           ║
# ║ Maps user-friendly input strings to internal calendar tags        ║
# ╚════════════════════════════════════════════════════════════════════╝
def resolve_input_to_tags(input_str: str, tag_names: dict, grouped_calendars: dict) -> list[str]:
    try:
        # Handle invalid inputs
        if not input_str or not isinstance(input_str, str):
            return []
            
        if not isinstance(tag_names, dict) or not isinstance(grouped_calendars, dict):
            logger.warning("Invalid tag_names or grouped_calendars provided to resolve_input_to_tags")
            return []
            
        requested = [s.strip().lower() for s in input_str.split(",") if s.strip()]
        matched = set()
        
        for item in requested:
            # First check for exact tag match (case insensitive)
            item_upper = item.upper()
            if item_upper in grouped_calendars:
                matched.add(item_upper)
                continue
                
            # Then check against display names
            matched_by_name = False
            for tag, name in tag_names.items():
                if not isinstance(name, str):
                    continue
                    
                if name.lower() == item:
                    matched.add(tag)
                    matched_by_name = True
                    break
                    
            if not matched_by_name:
                # Try partial matches if no exact match found
                for tag, name in tag_names.items():
                    if not isinstance(name, str):
                        continue
                        
                    if item in name.lower():
                        matched.add(tag)
                        break
                        
        return list(matched)
    except Exception as e:
        logger.exception(f"Error resolving input to tags: {e}")
        return []
