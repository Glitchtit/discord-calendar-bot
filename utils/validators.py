GOOGLE_CALENDAR_PATTERNS = [
    'calendar.google.com',
    'www.googleapis.com/calendar'
]

from datetime import datetime, timedelta

def detect_calendar_type(input_str: str) -> str | None:
    """Detects calendar type from input string.

    Args:
        input_str: User-provided calendar input

    Returns:
        str: Calendar type as 'google', 'ics', or 'webcal'
        None: If no recognizable pattern found
    """
    input_lower = input_str.lower()
    
    if any(pattern in input_lower for pattern in GOOGLE_CALENDAR_PATTERNS):
        return 'google'
    if input_lower.endswith('.ics'):
        return 'ics'
    if input_lower.startswith(('http://', 'https://')):
        return 'webcal'
    return None

def validate_event_dates(start: datetime, end: datetime) -> tuple[bool, str]:
    """Validate event date logic with enhanced checks."""
    if start >= end:
        return False, "Event must end after it starts"
        
    if start < datetime.now(tz=start.tzinfo):
        return False, "Events cannot be created in the past"
        
    if (end - start) > timedelta(days=14):
        return False, "Events cannot span more than 2 weeks"
        
    return True, ""
