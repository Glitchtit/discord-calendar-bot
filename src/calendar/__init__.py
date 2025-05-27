# Calendar Package
"""
Discord Calendar Bot - Calendar Package

This package handles calendar data management including:
- Google Calendar and ICS feed integration
- Event fetching, processing, and deduplication
- Calendar source configuration and user mappings
- Event data persistence and change detection
"""

from .sources import load_calendar_sources, get_user_tag_mapping
from .events import get_events, compute_event_fingerprint
from .storage import load_previous_events, save_current_events_for_key, clear_event_storage

__all__ = [
    'load_calendar_sources', 'get_user_tag_mapping',
    'get_events', 'compute_event_fingerprint',
    'load_previous_events', 'save_current_events_for_key', 'clear_event_storage'
]