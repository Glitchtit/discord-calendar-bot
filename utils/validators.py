GOOGLE_CALENDAR_PATTERNS = [
    'calendar.google.com',
    'www.googleapis.com/calendar'
]

def detect_calendar_type(input_str: str) -> str|None:
    """Detect calendar type from input string."""
    input_lower = input_str.lower()
    
    if any(pattern in input_lower for pattern in GOOGLE_CALENDAR_PATTERNS):
        return 'google'
    if input_lower.endswith('.ics'):
        return 'ics'
    if input_lower.startswith(('http://', 'https://')):
        return 'webcal'
    return None
