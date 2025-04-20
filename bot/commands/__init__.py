# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                    CALENDAR BOT COMMANDS PACKAGE INIT                    ║
# ║    Exports command handlers and shared utilities for the bot             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Initializes the bot.commands package.

This file serves two main purposes:
1.  Imports and re-exports the primary handler function from each command module
    (e.g., `handle_agenda_command` from `agenda.py`).
2.  Imports and re-exports shared utility functions used across multiple commands.
3.  Defines the `__all__` list, which specifies the symbols made available when
    using `from bot.commands import *`. This simplifies importing command handlers
    into the main command router.
"""

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ IMPORTS                                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Utility Imports ---
# Import shared utilities needed by command handlers.
# `send_embed` is imported via `command_router` to prevent circular dependencies.
from .utilities import check_channel_permissions
from ..command_router import send_embed # Import send_embed via command_router to avoid circular deps

# --- Command Handler Imports ---
# Import the main handler function from each command module.
# These functions contain the core logic for each slash command.
from .agenda import handle_agenda_command
from .clear import handle_clear_command
from .daily import handle_daily_command
from .greet import handle_greet_command
from .herald import handle_herald_command, post_tagged_events, post_tagged_week
from .reload import handle_reload_command
from .setup import handle_setup_command
from .status import handle_status_command
from .weekly import handle_weekly_command
from .who import handle_who_command

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EXPORT LIST (`__all__`)                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Export List (`__all__`) ---
# Defines which symbols are exported when `from bot.commands import *` is used.
# This makes the command handlers and essential utilities easily accessible
# to the command router (`bot/command_router.py`) for registration and dispatch.
__all__ = [
    # Command Handlers
    'handle_agenda_command',
    'handle_clear_command',
    'handle_daily_command',
    'handle_greet_command',
    'handle_herald_command',
    'handle_reload_command',
    'handle_setup_command',
    'handle_status_command',
    'handle_weekly_command',
    'handle_who_command',
    # Herald-specific posting functions (used by tasks)
    'post_tagged_events',
    'post_tagged_week',
    # Shared Utilities
    'check_channel_permissions',
    'send_embed',
]