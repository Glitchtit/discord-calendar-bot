"""
bot.py: Discord bot setup and initialization, including command sync and error handling.

This module implements the Discord bot interface including:
- Slash commands for calendar interaction
- Setup wizard for server-specific calendar configuration
- Event monitoring and notification systems

Note: Now uses server-specific configuration via /setup command instead of
the previous environment variable approach.
"""

import asyncio
from typing import List

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from discord.ui import View, Button, Select

from utils.logging import logger
from bot.events import (
    GROUPED_CALENDARS,
    USER_TAG_MAP,
    TAG_NAMES,
    TAG_COLORS,
    get_events,
    get_service_account_email,
    load_calendars_from_server_configs,
    reinitialize_events
)
from ai import generate_greeting, generate_image
from bot.commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
    handle_herald_command,
    handle_agenda_command,
    handle_greet_command,
    handle_reload_command,
    handle_who_command,
    handle_daily_command,
    handle_setup_command
)
from tasks import initialize_event_snapshots, start_all_tasks, post_todays_happenings
from utils import get_today, get_monday_of_week, resolve_input_to_tags
from utils.validators import detect_calendar_type
from config.server_config import (
    add_calendar, 
    remove_calendar, 
    load_server_config, 
    save_server_config,
    SERVER_CONFIG_DIR,
    get_all_server_ids
)
from collections import defaultdict
from datetime import timedelta
from bot.views import (
    CalendarSetupView,
    AddCalendarModal,
    CalendarRemoveView,
    ConfirmRemovalView
)
from config.calendar_config import CalendarConfig

# ╔════════════════════════════════════════════════════════════════════╗
# 🤖 Intents & Bot Setup
# ╚════════════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Track initialization state to avoid duplicate startups
bot.is_initialized = False


# ╔════════════════════════════════════════════════════════════════════╗
# ⚙️ on_ready: Sync Commands & Log Bot Info
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user}")
    
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return

    try:
        # Register bot client for admin notifications
        from utils.notifications import register_discord_client
        register_discord_client(bot)
        
        # Load admin users from config and register them for notifications
        from config.server_config import get_admin_user_ids
        from utils.notifications import register_admins
        admin_ids = get_admin_user_ids()
        if admin_ids:
            register_admins(admin_ids)
            logger.info(f"Registered {len(admin_ids)} admins for error notifications")
        else:
            logger.warning("No admin users configured for notifications")
        
        # Sync commands - only do this once during startup
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} commands.")

        # Initialize calendar configurations
        await resolve_tag_mappings()
        
        # Initialize event snapshots
        from tasks import initialize_event_snapshots
        await initialize_event_snapshots()
        
        # Set up real-time calendar subscriptions
        from utils.calendar_sync import initialize_subscriptions
        await initialize_subscriptions()
        
        # Start scheduled tasks
        from tasks import start_all_tasks
        await start_all_tasks(bot)
        
        # Mark initialization as complete
        bot.is_initialized = True
        logger.info("Bot initialization completed successfully")
    except Exception as e:
        logger.exception(f"Error during initialization: {e}")
        # Try to notify about the critical error
        try:
            from utils.notifications import notify_critical_error
            await notify_critical_error("Bot Initialization", e)
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")
        # Don't mark as initialized if an error occurs
        # This allows another attempt on reconnection


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_disconnect                                            ║
# ║ Called when the bot disconnects from Discord                ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord. Waiting for reconnection...")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔌 on_resumed                                               ║
# ║ Called when the bot reconnects after a disconnect           ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.event
async def on_resumed():
    logger.info("Bot connection resumed")
    
    try:
        # Check if any scheduled tasks need to be restarted
        from tasks import check_tasks_running, start_all_tasks
        
        # Verify all tasks are running, restart if needed
        tasks_status = await check_tasks_running()
        if not tasks_status:
            logger.warning("Some scheduled tasks were not running. Restarting tasks...")
            await start_all_tasks()
        
        # Refresh tag mappings to ensure they're up to date
        await resolve_tag_mappings()
        
        # Check for missed events during disconnection
        logger.info("Checking for any missed events during disconnection...")
        from tasks import check_for_missed_events
        await check_for_missed_events()
        
        logger.info("Connection recovery completed successfully")
    except Exception as e:
        logger.exception(f"Error during connection recovery: {e}")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📜 /herald                                                   ║
# ║ Posts the weekly + daily event summaries for all tags       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="herald",
    description="Get a summary of all users' weekly and daily events"
)
async def herald_command(interaction: discord.Interaction):
    await handle_herald_command(interaction)  # Delegate to the handler in commands.py


@bot.tree.command(
    name="agenda",
    description="See events for a specific date (natural language supported)"
)
async def agenda_command(interaction: discord.Interaction, date: str):
    await handle_agenda_command(interaction, date)  # Delegate to the handler in commands.py

@bot.tree.command(
    name="greet",
    description="Post the themed morning greeting with image"
)
async def greet_command(interaction: discord.Interaction):
    await handle_greet_command(interaction)  # Delegate to the handler in commands.py

@bot.tree.command(
    name="reload",
    description="Reload calendar sources and user mappings"
)
async def reload_command(interaction: discord.Interaction):
    await handle_reload_command(interaction)  # Delegate to the handler in commands.py

@bot.tree.command(
    name="who",
    description="List all calendars and their assigned users"
)
async def who_command(interaction: discord.Interaction):
    await handle_who_command(interaction)  # Delegate to the handler in commands.py

@bot.tree.command(
    name="daily",
    description="Post today's events for all users to the announcement channel"
)
async def daily_command(interaction: discord.Interaction):
    await handle_daily_command(interaction)  # Delegate to the handler in commands.py

# Removed setup_command implementation

# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔍 Autocomplete Functions                                    ║
# ║ Provides suggestions for command arguments                   ║
# ╚═════════════════════════════════════════════════════════════╝
async def autocomplete_agenda_input(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides autocomplete for date input in agenda command."""
    suggestions = [
        "today", "tomorrow", "week", 
        "next monday", "next tuesday", "next wednesday", 
        "next thursday", "next friday", "next saturday", "next sunday"
    ]
    
    # Add suggestions for upcoming days of the week
    today = get_today()
    for i in range(1, 7):
        day = (today + datetime.timedelta(days=i)).strftime("%A").lower()
        if day not in suggestions:
            suggestions.append(day)
    
    # Filter based on current input
    if current:
        return [
            app_commands.Choice(name=suggestion, value=suggestion)
            for suggestion in suggestions if current.lower() in suggestion.lower()
        ][:25]
    
    # Return top suggestions if no input
    return [app_commands.Choice(name=suggestion, value=suggestion) for suggestion in suggestions[:25]]

async def autocomplete_agenda_target(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Provides autocomplete for tag/user in agenda command."""
    suggestions = []
    
    # Add all tag names
    for tag in GROUPED_CALENDARS:
        display_name = TAG_NAMES.get(tag, tag)
        suggestions.append((display_name, display_name))
        # Also add the raw tag as an option
        if tag != display_name:
            suggestions.append((tag, tag))
    
    # Filter based on current input
    if current:
        filtered = [
            app_commands.Choice(name=name, value=value)
            for name, value in suggestions 
            if current.lower() in name.lower()
        ]
        return filtered[:25]  # Discord limits to 25 choices
    
    # Return all suggestions if no input
    return [app_commands.Choice(name=name, value=value) for name, value in suggestions[:25]]


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔗 resolve_tag_mappings                                      ║
# ║ Assigns display names and colors to tags based on members   ║
# ╚═════════════════════════════════════════════════════════════╝
async def resolve_tag_mappings():
    """Resolve user mappings and populate display names."""
    from bot.events import GROUPED_CALENDARS

    TAG_NAMES.clear()
    TAG_COLORS.clear()

    resolved_count = 0
    for guild in bot.guilds:
        try:
            for member in guild.members:
                if member.id in GROUPED_CALENDARS:
                    TAG_NAMES[member.id] = member.display_name
                    resolved_count += 1
        except Exception as e:
            logger.warning(f"Error resolving members for guild {guild.name}: {e}")

    logger.info(f"Resolved {resolved_count} user mappings to display names.")


# ╔═════════════════════════════════════════════════════════════════╗
# ║ 🧩 Setup UI Components                                          ║
# ║ Interactive components for the setup process                    ║
# ╚═════════════════════════════════════════════════════════════════╝

class CalendarSetupView(View):
    """Main view for the calendar setup wizard."""
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        
    @discord.ui.button(label="Add Calendar", style=discord.ButtonStyle.primary, emoji="➕")
    async def add_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Launch the add calendar modal when this button is clicked."""
        modal = AddCalendarModal(self.bot, self.guild_id)
        await interaction.response.send_modal(modal)
        
    @discord.ui.button(label="Remove Calendar", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def remove_calendar_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show a dropdown of calendars that can be removed."""
        # Load server config to get list of calendars
        config = load_server_config(self.guild_id)
        calendars = config.get("calendars", [])
        
        if not calendars:
            await interaction.response.send_message("No calendars configured for this server yet.", ephemeral=True)
            return
            
        # Create dropdown for calendar selection
        view = CalendarRemoveView(self.bot, self.guild_id, calendars)
        await interaction.response.send_message(
            "Select the calendar you want to remove:", 
            view=view, 
            ephemeral=True
        )
        
    @discord.ui.button(label="List Calendars", style=discord.ButtonStyle.secondary, emoji="📋")
    async def list_calendars_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """List all configured calendars."""
        await interaction.response.defer(ephemeral=True)
        config = load_server_config(self.guild_id)
        calendars = config.get("calendars", [])
        
        if not calendars:
            await interaction.followup.send(
                "No calendars configured for this server yet. Click 'Add Calendar' to get started.",
                ephemeral=True
            )
            return
            
        # Format calendar list
        lines = ["**Configured Calendars:**\n"]
        
        for i, cal in enumerate(calendars, 1):
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_id = cal.get("id", "unknown")
            cal_tag = cal.get("tag", "No Tag")
            user_id = cal.get("user_id", "Unknown User ID")
            user_name = TAG_NAMES.get(user_id, "Unknown User")
            
            # Truncate long calendar IDs
            display_id = cal_id[:27] + "..." if len(cal_id) > 30 else cal_id
                
            lines.append(
                f"{i}. **{cal_name}**\n"
                f"   ID: `{display_id}`\n"
                f"   User: **{user_name}** (ID: `{user_id}`)\n"
                f"   Tag: `{cal_tag}`"
            )
        
        await interaction.followup.send("\n".join(lines), ephemeral=True)

class AddCalendarModal(discord.ui.Modal):
    def __init__(self, bot, guild_id):
        super().__init__(title="Add Calendar")
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_input = discord.ui.TextInput(
            label="Calendar ID",
            placeholder="Enter the calendar ID",
            style=discord.TextInputStyle.short,
            required=True
        )
        self.add_item(self.calendar_input)

    async def callback(self, interaction: discord.Interaction):
        calendar_input = self.calendar_input.value
        detected_type = detect_calendar_type(calendar_input)
        if detected_type is None:
            await interaction.response.send_message("Invalid calendar ID. Please try again.", ephemeral=True)
            return
        
        calendar_data = {
            'type': detected_type,
            'id': calendar_input,
            'user_id': interaction.user.id
        }
        success, message = add_calendar(self.guild_id, calendar_data)
        if success:
            await interaction.response.send_message("Calendar added successfully!", ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
