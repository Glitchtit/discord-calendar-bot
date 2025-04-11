"""
commands.py: Core command registry and utilities setup
"""

import os
import discord
from datetime import datetime
from discord import Interaction
from typing import Optional

# Import shared components
from .views import CalendarSetupView
from utils.logging import logger

# Import command modules using relative imports
from .commands import (
    herald,
    agenda,
    greet,
    reload,
    who,
    daily,
    setup,
    utilities,
    status
)

# Get the send_embed function directly
send_embed = utilities.send_embed

async def setup_commands(bot: discord.Client):
    """Register all slash commands with the Discord bot"""
    logger.info("Registering command modules...")
    
    try:
        # Register all commands from their respective modules
        await herald.register(bot)
        await agenda.register(bot)
        await greet.register(bot)
        await reload.register(bot)
        await who.register(bot)
        await daily.register(bot)
        await setup.register(bot)
        await status.register(bot)  # Register our new status command
        
        logger.info(f"Registered all command modules successfully")
    except Exception as e:
        logger.exception(f"Error registering commands: {e}")

# Re-export command handlers for easier access
handle_daily_command = daily.handle_daily_command
handle_herald_command = herald.handle_herald_command
handle_agenda_command = agenda.handle_agenda_command
handle_greet_command = greet.handle_greet_command
handle_reload_command = reload.handle_reload_command
handle_who_command = who.handle_who_command
handle_setup_command = setup.handle_setup_command
handle_status_command = status.handle_status_command

# Export utility functions for command modules
__all__ = [
    'handle_daily_command',
    'handle_herald_command',
    'handle_agenda_command',
    'handle_greet_command',
    'handle_reload_command',
    'handle_who_command',
    'handle_setup_command',
    'handle_status_command',
    'send_embed'
]