"""
events package: Shell logic for event‑related functionality,
re‑exporting from submodules.
"""
from .google_api import *
from .calendar_loading import *
from .event_fetching import *
from .metadata import *
from .snapshot import *
from .fingerprint import *
from .reload import *

__all__ = [
    'service', 'credentials', 'get_service_account_email',
    'GROUPED_CALENDARS', 'TAG_NAMES', 'TAG_COLORS',
    'get_name_for_tag', 'get_color_for_tag', 'load_calendars_from_server_configs',
    'get_events', 'get_google_events', 'get_ics_events',
    'fetch_google_calendar_metadata', 'fetch_ics_calendar_metadata',
    'load_previous_events', 'save_current_events_for_key', 'load_post_tracking',
    'compute_event_fingerprint',
    'reinitialize_events', 'ensure_calendars_loaded', 'reinitialize_lock',
]
