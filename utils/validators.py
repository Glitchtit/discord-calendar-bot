from datetime import datetime, timedelta
from typing import Optional, Tuple, Union
import re
import logging
from googleapiclient.errors import HttpError  # Added missing import
import asyncio  # Added missing import
import requests  # Added missing import
logger = logging.getLogger("calendarbot")

def validate_event_dates(start: Optional[datetime], end: Optional[datetime]) -> Tuple[bool, str]:
    """
    Validate event date logic with enhanced checks.
    
    Args:
        start: The event start datetime (must have timezone info if using time)
        end: The event end datetime (must have timezone info if using time)
    
    Returns:
        Tuple containing (is_valid, error_message)
        - is_valid: Boolean indicating if the dates are valid
        - error_message: Empty string if valid, otherwise contains error reason
    
    Validation checks:
        1. Dates must not be None
        2. Event must end after it starts
        3. Event cannot be created in the past (small 5-min buffer allowed)
        4. Event cannot span more than 2 weeks
        5. Event cannot be scheduled more than 2 years in the future
    """
    # Check for None values
    if start is None or end is None:
        return False, "Event start and end dates must be provided"
    
    # Ensure both dates have timezone info if one does
    if start.tzinfo and not end.tzinfo:
        return False, "End date must have timezone information if start date does"
    elif end.tzinfo and not start.tzinfo:
        return False, "Start date must have timezone information if end date does"
        
    # Check event start is before end
    if start >= end:
        return False, "Event must end after it starts"
    
    # Get current time in the same timezone as the event
    now = datetime.now(tz=start.tzinfo)
    
    # Allow a small 5-minute buffer for event creation lag
    creation_buffer = now - timedelta(minutes=5)
    if start < creation_buffer:
        return False, "Events cannot be created in the past"
    
    # Check event duration
    if (end - start) > timedelta(days=14):
        return False, "Events cannot span more than 2 weeks"
    
    # Check if event is too far in the future
    max_future_date = now + timedelta(days=365*2)  # 2 years
    if start > max_future_date:
        return False, "Events cannot be scheduled more than 2 years in advance"
        
    return True, ""

def detect_calendar_type(url_or_id: str) -> str:
    """
    Detect calendar type based on the format of the input.
    
    Args:
        url_or_id: URL or ID string to analyze
        
    Returns:
        String indicating detected calendar type: 'google', 'ics', or 'unknown'
    """
    if not url_or_id:
        return "unknown"
        
    url_or_id = url_or_id.lower().strip()
    
    # Google Calendar detection patterns
    if (
        url_or_id.endswith("@group.calendar.google.com") or
        url_or_id.endswith("@gmail.com") or
        "calendar.google.com" in url_or_id
    ):
        return "google"
    
    # ICS calendar detection patterns
    if url_or_id.startswith(("http", "webcal")):
        # Check for common ICS indicators in URL
        ics_indicators = [
            ".ics",
            "ical",
            "calendar",
            "schedule",
            "/cal/",
            "calendar-share",
            "/export/",
            "/api/"  # Many calendar APIs provide ICS format
        ]
        
        for indicator in ics_indicators:
            if indicator in url_or_id:
                return "ics"
    
    return "unknown"

async def test_calendar_connection(calendar_type: str, calendar_id: str) -> Tuple[bool, str]:
    """
    Test a calendar connection to verify it's accessible.
    
    Args:
        calendar_type: Type of calendar ("google" or "ics")
        calendar_id: Calendar ID or URL
        
    Returns:
        Tuple of (success, message)
    """
    try:
        if calendar_type == "google":
            return await test_google_calendar(calendar_id)
        elif calendar_type == "ics":
            return await test_ics_calendar(calendar_id)
        else:
            return False, f"Unsupported calendar type: {calendar_type}"
    except Exception as e:
        logger.exception(f"Error testing calendar connection: {e}")
        return False, f"Error testing calendar: {str(e)}"

async def test_google_calendar(calendar_id: str) -> Tuple[bool, str]:
    """Test connection to a Google Calendar."""
    # Import here to avoid circular imports
    from bot.events import service, retry_api_call
    
    if not service:
        return False, "Google Calendar API not initialized"
    
    try:
        # Run API call in a thread pool to avoid blocking
        result = await asyncio.to_thread(
            retry_api_call,
            lambda: service.calendars().get(calendarId=calendar_id).execute(),
            max_retries=1  # Use fewer retries for testing
        )
        
        if not result:
            return False, "Failed to connect to calendar"
        
        # Get calendar name for better feedback
        name = result.get("summary", calendar_id)
        return True, f"Successfully connected to '{name}'"
        
    except HttpError as e:
        status_code = e.resp.status
        
        if status_code == 404:
            return False, "Calendar not found. Please verify the calendar ID."
        elif status_code == 403:
            return False, "Permission denied. Make sure the calendar is shared with the service account."
        else:
            return False, f"Google API error ({status_code}): {str(e)}"
    
    except Exception as e:
        return False, f"Error connecting to Google Calendar: {str(e)}"

async def test_ics_calendar(url: str) -> Tuple[bool, str]:
    """Test connection to an ICS calendar URL."""
    # Convert webcal:// to https:// for compatibility
    if url.startswith("webcal://"):
        url = "https://" + url[9:]
    
    try:
        # Run the request in a thread pool to avoid blocking
        response = await asyncio.to_thread(
            lambda: requests.head(url, timeout=5)
        )
        
        if response.status_code == 200:
            # Try to extract a meaningful name from the URL
            if "?" in url:
                url_parts = url.split("?")[0].split("/")
            else:
                url_parts = url.split("/")
                
            name = next((part for part in reversed(url_parts) if part), "ICS Calendar")
            return True, f"Successfully connected to '{name}'"
        else:
            return False, f"Failed to connect to ICS URL: HTTP {response.status_code}"
            
    except requests.exceptions.ConnectionError:
        return False, "Failed to connect to URL. Check that it's accessible."
    except requests.exceptions.Timeout:
        return False, "Connection timed out. The server may be slow or unreachable."
    except Exception as e:
        return False, f"Error connecting to ICS calendar: {str(e)}"
