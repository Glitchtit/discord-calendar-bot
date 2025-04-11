"""
commands.py: Core command registry and utilities setup
"""

import os
import discord
from datetime import datetime
from discord import Interaction
from typing import Optional

# Import command modules
from .commands import (
    herald,
    agenda,
    greet,
    reload,
    who,
    daily
)

# Import shared components
from .views import CalendarSetupView
from .utilities import _retry_discord_operation, send_embed
from utils import validate_env_vars
from utils.logging import logger
from .setup import setup

# Initialize critical environment variables
validate_env_vars(["ANNOUNCEMENT_CHANNEL_ID", "DISCORD_BOT_TOKEN"])

async def setup_commands(bot: discord.Client):
    """Register all slash commands with the Discord bot"""
    
    # Register all commands
    await setup(bot)  # Initialize setup command

    @bot.tree.command(name="herald")
    async def herald_command(interaction: Interaction):
        """Post today's events for your calendars"""
        await herald.post_tagged_events(interaction, datetime.today())

    @bot.tree.command(name="agenda")
    async def agenda_command(interaction: Interaction, date: str):
        """Get events for a specific date"""
        await agenda.handle_agenda_command(interaction, date)

    @bot.tree.command(name="greet")
    async def greet_command(interaction: Interaction):
        """Post morning greeting with generated image"""
        await greet.handle_greet_command(interaction)

    @bot.tree.command(name="reload")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def reload_command(interaction: Interaction):
        """Reload calendar configurations (Admin only)"""
        await reload.handle_reload_command(interaction)

    @bot.tree.command(name="who")
    async def who_command(interaction: Interaction):
        """List configured calendars and users"""
        await who.handle_who_command(interaction)

    @bot.tree.command(name="daily")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def daily_command(interaction: Interaction):
        """Post daily summaries to announcement channel"""
        await daily.handle_daily_command(interaction)

    # Add error handling for privileged commands
    @reload_command.error
    @daily_command.error
    async def privileged_command_error(interaction: Interaction, error):
        if isinstance(error, discord.app_commands.MissingPermissions):
            await interaction.response.send_message(
                "⛔ This command requires special permissions",
                ephemeral=True
            )
        else:
            logger.error(f"Command error: {error}")
            await interaction.response.send_message(
                "⚠️ An error occurred executing this command",
                ephemeral=True
            )