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
# 📆 Date Utilities
# ╚════════════════════════════════════════════════════════════════════╝

def get_today() -> date:
    try:
        return datetime.now(tz=get_local_timezone()).date()
    except Exception as e:
        logger.exception(f"Error getting today's date: {e}. Using UTC.")
        # Fallback to UTC in case of error
        return datetime.now(tz=tz.UTC).date()


# ╔════════════════════════════════════════════════════════════════════╗
# ✨ Event Formatting
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
# ║ 🔤 emoji_for_event                                                 ║
# ║ Attempts to guess an emoji based on event title                    ║
# ╚════════════════════════════════════════════════════════════════════╝
def emoji_for_event(title: str) -> str:
    # Handle None or non-string inputs
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
        # Handle date-only format (YYYY-MM-DD)
        if _date_str_pattern.match(date_str):
            return datetime.fromisoformat(date_str)
            
        # Handle Z (UTC) timezone indicator
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
            
        # Handle missing timezone information
        if '+' not in date_str and '-' not in date_str[-6:]:
            # If no timezone info, assume UTC then convert to local
            dt = datetime.fromisoformat(date_str)
            dt = dt.replace(tzinfo=tz.UTC)
            return dt.astimezone(default_timezone)
            
        # Normal case with timezone info
        return datetime.fromisoformat(date_str)
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse date string '{date_str}': {e}")
        return None


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📝 format_event                                                    ║
# ║ Converts an event dictionary into a stylized, readable string     ║
# ╚════════════════════════════════════════════════════════════════════╝
def format_event(event: dict) -> str:
    try:
        # Validate event data
        if not event or not isinstance(event, dict):
            logger.warning(f"Invalid event data: {event}")
            return "⚠️ **Invalid event data**"
            
        # Get event start/end times with validation
        start_data = event.get("start", {})
        end_data = event.get("end", {})
        
        if not isinstance(start_data, dict) or not isinstance(end_data, dict):
            logger.warning(f"Invalid start/end data format in event: {event}")
            return "⚠️ **Invalid event format**"
            
        start = start_data.get("dateTime", start_data.get("date", ""))
        end = end_data.get("dateTime", end_data.get("date", ""))
        
        # Get and sanitize title (prevent markdown injection)
        title = event.get("summary", "Untitled")
        if isinstance(title, str):
            # Truncate long titles to prevent display issues
            if len(title) > 50:
                title = title[:47] + "..."
            # Escape characters that could break markdown formatting
            title = title.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
        else:
            title = "Untitled"
            
        # Get and sanitize location
        location = event.get("location", "")
        if isinstance(location, str):
            location = location.replace("*", "\\*").replace("_", "\\_")
        else:
            location = ""
            
        # Get appropriate emoji
        emoji = emoji_for_event(title)

        # Parse start time
        local_timezone = get_local_timezone()
        start_str = "All Day"
        
        if start and "T" in start:
            start_dt = parse_date_string(start, local_timezone)
            if start_dt:
                start_str = start_dt.strftime("%H:%M")

        # Parse end time
        end_str = ""
        if end and "T" in end:
            end_dt = parse_date_string(end, local_timezone)
            if end_dt:
                end_str = end_dt.strftime("%H:%M")

        # Format the time range and location
        time_range = f"{start_str}–{end_str}" if end_str else start_str
        location_str = f" *({location})*" if location else ""

        return f"{emoji} **{title}** `{time_range}`{location_str}"
    except Exception as e:
        logger.exception(f"Error formatting event: {e}")
        return "⚠️ **Error formatting event**"


# ╔════════════════════════════════════════════════════════════════════╗
# 🔤 Tag Resolution
# ╚════════════════════════════════════════════════════════════════════╝
def is_in_current_week(event: dict, reference: date = None) -> bool:
    try:
        # Validate inputs
        if not event or not isinstance(event, dict):
            return False
            
        reference = reference or get_today()
        monday = get_monday_of_week(reference)
        week_range = {monday + timedelta(days=i) for i in range(7)}
        
        # Get and validate start date
        start_data = event.get("start", {})
        if not isinstance(start_data, dict):
            return False
            
        start_str = start_data.get("dateTime", start_data.get("date", ""))
        if not start_str:
            return False
            
        # Parse the date
        dt = parse_date_string(start_str)
        if not dt:
            return False
            
        return dt.date() in week_range
    except Exception as e:
        logger.exception(f"Error checking if event is in current week: {e}")
        return False


def resolve_input_to_tags(input_text: str, tag_names: dict, grouped_calendars: dict) -> list:
    """
    Resolves user input text to a list of calendar tags.
    
    Args:
        input_text: The text to resolve (could be a tag ID, display name, or partial match)
        tag_names: Dictionary mapping tag IDs to display names
        grouped_calendars: Dictionary of available calendars grouped by tag
        
    Returns:
        List of matching tag IDs
    """
    if not input_text or not input_text.strip():
        return list(grouped_calendars.keys())
    
    input_lower = input_text.lower().strip()
    matches = []
    
    # Check for exact match with tag ID first
    if input_text in grouped_calendars:
        return [input_text]
    
    # Look for matches in tag names (case-insensitive)
    for tag_id, name in tag_names.items():
        if input_lower == name.lower():
            return [tag_id]  # Exact display name match
        if input_lower in name.lower():
            matches.append(tag_id)  # Partial display name match
    
    # If we found partial matches, return those
    if matches:
        return matches
    
    # Try partial matches with tag IDs as a last resort
    for tag_id in grouped_calendars:
        if input_lower in str(tag_id).lower():
            matches.append(tag_id)
    
    return matches
