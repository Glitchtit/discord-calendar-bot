"""
timezone_utils.py: Standardized timezone handling across the application

This module provides consistent timezone handling functions to ensure event times
are displayed correctly across different calendar sources.
"""

from datetime import datetime, date, time, timedelta
import re
from typing import Optional, Union, Dict, Any, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging

logger = logging.getLogger("calendarbot")

# Default timezone to use if none is specified
DEFAULT_TIMEZONE = "UTC"

# Common timezone mappings for user-friendly display
COMMON_TIMEZONE_ALIASES = {
    "est": "America/New_York",
    "cst": "America/Chicago",
    "mst": "America/Denver",
    "pst": "America/Los_Angeles",
    "edt": "America/New_York",
    "cdt": "America/Chicago",
    "mdt": "America/Denver",
    "pdt": "America/Los_Angeles",
    "gmt": "UTC",
    "utc": "UTC"
}

def get_timezone(tz_name: str) -> ZoneInfo:
    """
    Get a ZoneInfo object for the specified timezone name.
    
    Args:
        tz_name: Timezone name or alias
        
    Returns:
        ZoneInfo object for the timezone
    
    Falls back to UTC if the timezone is invalid.
    """
    if not tz_name:
        return ZoneInfo(DEFAULT_TIMEZONE)
    
    # Normalize timezone name
    tz_name = tz_name.lower().strip()
    
    # Check for common aliases
    if tz_name in COMMON_TIMEZONE_ALIASES:
        tz_name = COMMON_TIMEZONE_ALIASES[tz_name]
    
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        logger.warning(f"Invalid timezone '{tz_name}', falling back to {DEFAULT_TIMEZONE}: {e}")
        return ZoneInfo(DEFAULT_TIMEZONE)

def get_user_timezone(user_id: str, source_meta: Optional[Dict[str, Any]] = None) -> ZoneInfo:
    """
    Get the appropriate timezone for a user, with fallbacks.
    
    Args:
        user_id: Discord user ID
        source_meta: Optional calendar source metadata with timezone info
        
    Returns:
        ZoneInfo object for the user's timezone
    """
    # Try to get from user preferences (future implementation)
    # For now, use calendar timezone if available, otherwise default
    if source_meta and "timezone" in source_meta:
        return get_timezone(source_meta["timezone"])
    
    # Default timezone
    return ZoneInfo(DEFAULT_TIMEZONE)

def parse_datetime(dt_str: str, timezone: Optional[Union[str, ZoneInfo]] = None) -> datetime:
    """
    Parse a datetime string into a timezone-aware datetime object.
    
    Args:
        dt_str: Datetime string to parse
        timezone: Optional timezone to apply if the string has no timezone
        
    Returns:
        Timezone-aware datetime object
    """
    # Convert timezone string to ZoneInfo if needed
    if isinstance(timezone, str):
        timezone = get_timezone(timezone)
    elif timezone is None:
        timezone = ZoneInfo(DEFAULT_TIMEZONE)
    
    # Normalize string and handle common formats
    dt_str = dt_str.strip()
    
    # Handle 'Z' UTC indicator
    if dt_str.endswith('Z'):
        dt_str = dt_str[:-1] + '+00:00'
    
    # Try parsing the datetime
    try:
        # Check if the string already has timezone info
        if any(c in dt_str for c in ['+', '-', 'Z']) and 'T' in dt_str:
            # Already timezone-aware
            dt = datetime.fromisoformat(dt_str)
            # Convert to the target timezone if needed
            if dt.tzinfo is not None and timezone is not None:
                dt = dt.astimezone(timezone)
            return dt
        else:
            # No timezone specified, assume the provided timezone
            # Handle both date-only and datetime formats
            if 'T' not in dt_str and len(dt_str) <= 10:
                # Date only format (YYYY-MM-DD)
                d = date.fromisoformat(dt_str)
                return datetime.combine(d, time.min, tzinfo=timezone)
            else:
                # Try to parse as datetime without timezone
                dt = datetime.fromisoformat(dt_str)
                # Attach timezone if not present
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone)
                return dt
    except (ValueError, TypeError) as e:
        logger.warning(f"Error parsing datetime '{dt_str}': {e}")
        # Return current time as fallback
        return datetime.now(timezone)

def format_event_time(event: Dict[str, Any], user_timezone: Optional[ZoneInfo] = None) -> str:
    """
    Format an event's time in a user-friendly way, accounting for timezones.
    
    Args:
        event: Event dictionary 
        user_timezone: Optional timezone to display the time in
        
    Returns:
        Formatted time string
    """
    if not event:
        return "Unknown time"
    
    # Default to UTC if no timezone provided
    if user_timezone is None:
        user_timezone = ZoneInfo(DEFAULT_TIMEZONE)
    
    # Get start time
    start_container = event.get("start", {})
    
    # Handle all-day events
    if "date" in start_container:
        # All-day event
        start_date = date.fromisoformat(start_container["date"])
        return f"All day on {start_date.strftime('%A, %B %d, %Y')}"
    
    # Handle timed events
    if "dateTime" in start_container:
        start_dt = parse_datetime(start_container["dateTime"], user_timezone)
        end_container = event.get("end", {})
        
        # For timed events, also include end time
        if "dateTime" in end_container:
            end_dt = parse_datetime(end_container["dateTime"], user_timezone)
            
            # Same day format
            if start_dt.date() == end_dt.date():
                return (
                    f"{start_dt.strftime('%A, %B %d, %Y')} "
                    f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')} "
                    f"{user_timezone.key}"
                )
            # Different day format
            else:
                return (
                    f"{start_dt.strftime('%A, %B %d, %Y %I:%M %p')} - "
                    f"{end_dt.strftime('%A, %B %d, %Y %I:%M %p')} "
                    f"{user_timezone.key}"
                )
        
        # Only have start time
        return f"{start_dt.strftime('%A, %B %d, %Y %I:%M %p')} {user_timezone.key}"
    
    # If we can't find a proper time format
    return "Time not specified"