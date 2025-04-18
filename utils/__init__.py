from .validators import validate_event_dates
from .server_utils import (
    load_server_config, 
    save_server_config,
    detect_calendar_type,
    migrate_env_config_to_server,
    get_all_server_ids
)

# Add the import for our new module to make it available
from .message_formatter import (
    format_daily_message,
    format_weekly_message,
    format_agenda_message,
    format_event_markdown
)

# Import common utility functions from root utils.py file
# These are used throughout the codebase
import sys
import importlib.util
import os
from pathlib import Path

# Dynamically import utils.py from parent directory
try:
    parent_dir = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location("root_utils", parent_dir / "utils.py")
    root_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(root_utils)
    
    # Import essential functions from utils.py
    get_monday_of_week = root_utils.get_monday_of_week
    get_today = root_utils.get_today
    format_event = root_utils.format_event
    resolve_input_to_tags = root_utils.resolve_input_to_tags
    is_in_current_week = root_utils.is_in_current_week
    format_message_lines = root_utils.format_message_lines
    emoji_for_event = root_utils.emoji_for_event
except Exception as e:
    import logging
    logging.exception(f"Error importing from root utils.py: {e}")
    # Provide stubs to prevent errors
    def get_monday_of_week(*args, **kwargs): pass
    def get_today(*args, **kwargs): pass
    def format_event(*args, **kwargs): return "Error formatting event"
    def resolve_input_to_tags(*args, **kwargs): return []
    def is_in_current_week(*args, **kwargs): return False
    def format_message_lines(*args, **kwargs): return []
    def emoji_for_event(*args, **kwargs): return "•"

def split_message_by_lines(message: str, limit: int) -> list[str]:
    """Splits a message by lines, ensuring no chunk exceeds the limit."""
    lines = message.split('\n')
    chunks = []
    current_chunk = ""
    for line in lines:
        # Check if adding the next line (plus newline char) exceeds the limit
        if len(current_chunk) + len(line) + 1 > limit:
            # If the current chunk is not empty, add it to the list
            if current_chunk:
                chunks.append(current_chunk)
            # If a single line exceeds the limit, split the line itself (rare case)
            if len(line) > limit:
                # Simple split, might break markdown
                for i in range(0, len(line), limit):
                    chunks.append(line[i:i+limit])
                current_chunk = "" # Reset chunk after handling oversized line
            else:
                current_chunk = line # Start new chunk with the current line
        else:
            # Add line to current chunk
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    # Add the last remaining chunk if it's not empty
    if current_chunk:
        chunks.append(current_chunk)

    # If the original message was empty or only whitespace
    if not chunks and not message.strip():
        return []
    # If message splitting resulted in no chunks but message wasn't empty (e.g. single long line)
    elif not chunks and message:
         # Fallback: split purely by character limit if line splitting failed
         return [message[i:i + limit] for i in range(0, len(message), limit)]

    return chunks

__all__ = [
    'detect_calendar_type',
    'validate_event_dates',
    'load_server_config',
    'save_server_config',
    'migrate_env_config_to_server',
    'get_all_server_ids',
    # Add exported utility functions
    'get_monday_of_week',
    'get_today',
    'format_event',
    'resolve_input_to_tags',
    'is_in_current_week',
    'format_message_lines',
    'emoji_for_event',
    'split_message_by_lines'
]
