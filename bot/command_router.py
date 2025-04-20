# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                     COMMAND ROUTER & REGISTRATION                        ║
# ║ Dynamically imports, registers, and routes slash commands to their modules ║
# ╚════════════════════════════════════════════════════════════════════════════╝
"""
commands.py: Core command registry and utilities setup
"""

import os
import discord
from datetime import datetime
from discord import Interaction
from typing import Optional
import importlib
import sys
from pathlib import Path

# Import shared components
from .views import CalendarSetupView
from utils.logging import logger

# --- import_command_module ---
# Dynamically imports a command module from the `bot.commands` package.
# This helps avoid circular dependencies between command modules and the router.
# Args:
#     module_name: The name of the command module file (without .py).
# Returns: The imported module object.
# Raises: ImportError if the module cannot be found.
def import_command_module(module_name):
    # Construct the full module path
    full_module_path = f"bot.commands.{module_name}"
    
    # Check if the module is already imported
    if full_module_path in sys.modules:
        # Reload the module if it's already imported (useful for development/reloading)
        # return importlib.reload(sys.modules[full_module_path])
        # For production, just return the existing module
        return sys.modules[full_module_path]
        
    # Dynamically import the module
    try:
        module = importlib.import_module(full_module_path)
        logger.debug(f"Dynamically imported module: {full_module_path}")
        return module
    except ImportError as e:
        logger.error(f"Failed to import command module '{module_name}': {e}")
        raise # Re-raise the exception to indicate failure

# --- setup_commands ---
# Imports all known command modules and calls their respective `register` functions.
# This makes the slash commands available to Discord.
# Args:
#     bot: The discord.Client instance.
async def setup_commands(bot: discord.Client):
    """Register all slash commands with the Discord bot"""
    logger.info("Registering command modules...")
    
    try:
        # Import command modules dynamically to avoid circular imports
        herald = import_command_module("herald")
        agenda = import_command_module("agenda")
        greet = import_command_module("greet")
        reload_mod = import_command_module("reload")  # renamed to avoid conflict with built-in reload
        who = import_command_module("who")
        daily = import_command_module("daily")
        setup = import_command_module("setup")
        status = import_command_module("status")
        weekly = import_command_module("weekly") # Added weekly import
        clear = import_command_module("clear") # Added clear import
        
        # Register all commands from their respective modules
        await herald.register(bot)
        await agenda.register(bot)
        await greet.register(bot)
        await reload_mod.register(bot)
        await who.register(bot)
        await daily.register(bot)
        await setup.register(bot)
        await status.register(bot)
        await weekly.register(bot) # Added weekly registration
        await clear.register(bot) # Added clear registration
        
        logger.info(f"Registered all command modules successfully")
    except Exception as e:
        logger.exception(f"Error registering commands: {e}")

# --- handle_daily_command ---
# Wrapper to dynamically import and call the handler for the /daily command.
# Args:
#     interaction: The discord.Interaction object.
def handle_daily_command(interaction):
    daily = import_command_module("daily")
    return daily.handle_daily_command(interaction)
    
# --- handle_herald_command ---
# Wrapper to dynamically import and call the handler for the /herald command.
# Args:
#     interaction: The discord.Interaction object.
def handle_herald_command(interaction):
    herald = import_command_module("herald")
    return herald.handle_herald_command(interaction)
    
# --- handle_agenda_command ---
# Wrapper to dynamically import and call the handler for the /agenda command.
# Args:
#     interaction: The discord.Interaction object.
#     date: The specific date for the agenda.
def handle_agenda_command(interaction, date):
    agenda = import_command_module("agenda")
    return agenda.handle_agenda_command(interaction, date)
    
# --- handle_greet_command ---
# Wrapper to dynamically import and call the handler for the /greet command.
# Args:
#     interaction: The discord.Interaction object.
def handle_greet_command(interaction):
    greet = import_command_module("greet")
    return greet.handle_greet_command(interaction)
    
# --- handle_reload_command ---
# Wrapper to dynamically import and call the handler for the /reload command.
# Args:
#     interaction: The discord.Interaction object.
def handle_reload_command(interaction):
    reload_mod = import_command_module("reload")
    return reload_mod.handle_reload_command(interaction)
    
# --- handle_who_command ---
# Wrapper to dynamically import and call the handler for the /who command.
# Args:
#     interaction: The discord.Interaction object.
def handle_who_command(interaction):
    who = import_command_module("who")
    return who.handle_who_command(interaction)
    
# --- handle_setup_command ---
# Wrapper to dynamically import and call the handler for the /setup command.
# Args:
#     interaction: The discord.Interaction object.
def handle_setup_command(interaction):
    setup = import_command_module("setup")
    return setup.handle_setup_command(interaction)
    
# --- handle_status_command ---
# Wrapper to dynamically import and call the handler for the /status command.
# Args:
#     interaction: The discord.Interaction object.
def handle_status_command(interaction):
    status = import_command_module("status")
    return status.handle_status_command(interaction)

# --- handle_weekly_command ---
# Wrapper to dynamically import and call the handler for the /weekly command.
# Args:
#     interaction: The discord.Interaction object.
def handle_weekly_command(interaction):
    weekly = import_command_module("weekly")
    return weekly.handle_weekly_command(interaction)

# --- handle_clear_command ---
# Wrapper to dynamically import and call the handler for the /clear command.
# Args:
#     interaction: The discord.Interaction object.
def handle_clear_command(interaction):
    clear = import_command_module("clear")
    return clear.handle_clear_command(interaction)

# --- post_tagged_events ---
# Wrapper to dynamically import and call `post_tagged_events` from the herald module.
# Args:
#     interaction: The discord.Interaction object.
#     day: The specific day to post events for.
def post_tagged_events(interaction, day):
    herald = import_command_module("herald")
    return herald.post_tagged_events(interaction, day)

# --- post_tagged_week ---
# Wrapper to dynamically import and call `post_tagged_week` from the herald module.
# Args:
#     interaction: The discord.Interaction object.
#     monday: The Monday of the week to post events for.
def post_tagged_week(interaction, monday):
    herald = import_command_module("herald")
    return herald.post_tagged_week(interaction, monday)

# --- send_embed ---
# Wrapper to dynamically import and call `send_embed` from the utilities module.
# Args:
#     *args: Positional arguments for send_embed.
#     **kwargs: Keyword arguments for send_embed.
def send_embed(*args, **kwargs):
    utilities = import_command_module("utilities")
    return utilities.send_embed(*args, **kwargs)

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
    'send_embed',
    'post_tagged_events',
    'post_tagged_week',
    'handle_weekly_command',
    'handle_clear_command'
]