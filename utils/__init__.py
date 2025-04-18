# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        CALENDAR BOT UTILS PACKAGE INIT                   ║
# ║    Exports utility functions and dynamic imports for shared helpers      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from .validators import validate_event_dates
from .server_utils import (
    load_server_config, 
    save_server_config,
    detect_calendar_type,
    migrate_env_config_to_server,
    get_all_server_ids
)
from .message_formatter import (
    format_daily_message,
    format_weekly_message,
    format_agenda_message,
    format_event_markdown
)
import sys
import importlib.util
import os
from pathlib import Path
try:
    parent_dir = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location("root_utils", parent_dir / "utils.py")
    root_utils = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(root_utils)
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
    def get_monday_of_week(*args, **kwargs): pass
    def get_today(*args, **kwargs): pass
    def format_event(*args, **kwargs): return "Error formatting event"
    def resolve_input_to_tags(*args, **kwargs): return []
    def is_in_current_week(*args, **kwargs): return False
    def format_message_lines(*args, **kwargs): return []
    def emoji_for_event(*args, **kwargs): return "•"
def split_message_by_lines(message: str, limit: int) -> list[str]:
    lines = message.split('\n')
    chunks = []
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > limit:
            if current_chunk:
                chunks.append(current_chunk)
            if len(line) > limit:
                for i in range(0, len(line), limit):
                    chunks.append(line[i:i+limit])
                current_chunk = ""
            else:
                current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line
    if current_chunk:
        chunks.append(current_chunk)
    if not chunks and not message.strip():
        return []
    elif not chunks and message:
         return [message[i:i + limit] for i in range(0, len(message), limit)]
    return chunks
__all__ = [
    'detect_calendar_type',
    'validate_event_dates',
    'load_server_config',
    'save_server_config',
    'migrate_env_config_to_server',
    'get_all_server_ids',
    'get_monday_of_week',
    'get_today',
    'format_event',
    'resolve_input_to_tags',
    'is_in_current_week',
    'format_message_lines',
    'emoji_for_event',
    'split_message_by_lines'
]
