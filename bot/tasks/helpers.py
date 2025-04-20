# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                       BOT TASKS HELPERS MODULE                       ║
# ║ Provides helper functions to dynamically import command functions, avoiding║
# ║ circular dependencies between the `tasks` and `commands` modules.        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Helper functions for tasks to avoid circular imports.

This module provides bridges to external modules needed by tasks.
"""
from utils.logging import logger

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ DYNAMIC IMPORTERS                                                         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_post_daily_events_function ---
# Dynamically imports and returns the `post_daily_events` function from `bot.commands.daily`.
# Used by tasks that need to trigger the daily event posting command.
# Returns: The `post_daily_events` function object.
async def get_post_daily_events_function():
    """Get the post_daily_events function without import-time circular dependency."""
    from bot.commands.daily import post_daily_events
    return post_daily_events

# --- get_post_weekly_events_function ---
# Dynamically imports and returns the `post_weekly_events` function from `bot.commands.weekly`.
# Used by tasks that need to trigger the weekly event posting command.
# Returns: The `post_weekly_events` function object.
async def get_post_weekly_events_function():
    """Get the post_weekly_events function without import-time circular dependency."""
    from bot.commands.weekly import post_weekly_events
    return post_weekly_events

# --- get_post_greeting_function ---
# Dynamically imports and returns the `post_greeting` function from `bot.commands.greet`.
# Used by tasks that need to trigger the greeting command.
# Returns: The `post_greeting` function object.
async def get_post_greeting_function():
    """Get the post_greeting function without import-time circular dependency."""
    from bot.commands.greet import post_greeting
    return post_greeting
