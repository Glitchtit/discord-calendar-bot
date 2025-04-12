"""
Helper functions for tasks to avoid circular imports.

This module provides bridges to external modules needed by tasks.
"""
from utils.logging import logger

async def get_post_daily_events_function():
    """Get the post_daily_events function without import-time circular dependency."""
    from bot.commands.daily import post_daily_events
    return post_daily_events

async def get_post_weekly_events_function():
    """Get the post_weekly_events function without import-time circular dependency."""
    from bot.commands.weekly import post_weekly_events
    return post_weekly_events

async def get_post_greeting_function():
    """Get the post_greeting function without import-time circular dependency."""
    from bot.commands.greet import post_greeting
    return post_greeting
