"""
bot.py: Discord bot setup and initialization, including command sync and error handling.

This module implements the Discord bot interface including:
- Slash commands for calendar interaction
- Setup wizard for server-specific calendar configuration
- Event monitoring and notification systems

Note: Now uses server-specific configuration via /setup command instead of
the previous environment variable approach.
"""

import sys
import asyncio
from typing import Any, List

import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import dateparser
import asyncio
import random
import os
from discord.ui import View, Button, Select, Modal, TextInput

from log import logger
from events import (
    GROUPED_CALENDARS,
    USER_TAG_MAP,
    TAG_NAMES,
    TAG_COLORS,
    get_events,
    get_service_account_email,
    load_calendars_from_server_configs
)
from ai import generate_greeting, generate_image
from commands import (
    post_tagged_events,
    post_tagged_week,
    send_embed,
)
from tasks import initialize_event_snapshots, start_all_tasks, post_todays_happenings
from utils import get_today, get_monday_of_week, resolve_input_to_tags
from server_config import (
    add_calendar, 
    remove_calendar, 
    load_server_config, 
    save_server_config,
    SERVER_CONFIG_DIR,
    get_all_server_ids,
    detect_calendar_type
)

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
    
    # Prevent multiple initializations if Discord reconnects
    if bot.is_initialized:
        logger.info("Bot reconnected, skipping initialization")
        return
    
    # Perform initialization with progressive backoff for retries
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # Step 1: Load calendars from server configurations
            load_calendars_from_server_configs()
            
            # Step 2: Resolve tag mappings
            await resolve_tag_mappings()
            
            # Step 3: Add slight delay to avoid rate limiting
            await asyncio.sleep(1)
            
            # Step 4: Sync slash commands
            synced = await bot.tree.sync()
            logger.info(f"Synced {len(synced)} commands.")
            
            # Step 5: Initialize event snapshots
            await initialize_event_snapshots()
            
            # Step 6: Start recurring tasks
            start_all_tasks(bot)
            
            # Step 7: Send migration guidance message to admins
            await send_migration_guidance()
            
            # Mark successful initialization
            bot.is_initialized = True
            logger.info("Bot initialization completed successfully")
            break
            
        except discord.errors.HTTPException as e:
            # Handle Discord API issues with exponential backoff
            retry_delay = 2 ** attempt + random.uniform(0, 1)
            logger.warning(f"Discord API error during initialization (attempt {attempt}/{max_retries}): {e}")
            
            if attempt < max_retries:
                logger.info(f"Retrying initialization in {retry_delay:.2f} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Maximum retries reached. Continuing with partial initialization.")
                # Still mark as initialized to prevent endless retries on reconnect
                bot.is_initialized = True
                
        except Exception as e:
            logger.exception(f"Unexpected error during initialization: {e}")
            # Mark as initialized despite error to prevent retry loops
            bot.is_initialized = True


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


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📜 /herald                                                   ║
# ║ Posts the weekly + daily event summaries for all tags       ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="herald",
    description="Post all weekly and daily events for every calendar tag"
)
async def herald_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        today = get_today()
        monday = get_monday_of_week(today)

        for tag in GROUPED_CALENDARS:
            await post_tagged_week(bot, tag, monday)
        for tag in GROUPED_CALENDARS:
            await post_tagged_events(bot, tag, today)

        await interaction.followup.send("Herald posted for **all** tags — week and today.")
    except Exception as e:
        logger.exception(f"Error in /herald command: {e}")
        await interaction.followup.send("An error occurred while posting the herald.")


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
# ║ 🗓️ /agenda                                                   ║
# ║ Posts events for a given date or natural language input     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="agenda",
    description="Post events for a date or range (e.g. 'tomorrow', 'week'), with optional tag filter"
)
@app_commands.describe(
    input="A natural date or keyword: 'today', 'week', 'next monday', 'April 10', 'DD.MM'",
    target="Optional calendar tag or display name (e.g. Bob, xXsNiPeRkId69Xx)"
)
@app_commands.autocomplete(input=autocomplete_agenda_input, target=autocomplete_agenda_target)
async def agenda_command(interaction: discord.Interaction, input: str, target: str = ""):
    try:
        await interaction.response.defer()

        today = get_today()
        tags = resolve_input_to_tags(target, TAG_NAMES, GROUPED_CALENDARS) if target.strip() else list(GROUPED_CALENDARS.keys())

        if not tags:
            await interaction.followup.send("No matching tags or names found.")
            return

        any_posted = False
        if input.lower() == "today":
            for tag in tags:
                posted = await post_tagged_events(bot, tag, today)
                any_posted |= posted
            label = today.strftime("%A, %B %d")
        elif input.lower() == "week":
            monday = get_monday_of_week(today)
            for tag in tags:
                await post_tagged_week(bot, tag, monday)
            any_posted = True  # Weekly always posts if calendars are valid
            label = f"week of {monday.strftime('%B %d')}"
        else:
            parsed = dateparser.parse(input)
            if not parsed:
                await interaction.followup.send("Could not understand the date. Try 'today', 'week', or a real date.")
                return
            day = parsed.date()
            for tag in tags:
                posted = await post_tagged_events(bot, tag, day)
                any_posted |= posted
            label = day.strftime("%A, %B %d")

        tag_names = ", ".join(TAG_NAMES.get(t, t) for t in tags)
        if any_posted:
            await interaction.followup.send(f"Agenda posted for **{tag_names}** on **{label}**.")
        else:
            await interaction.followup.send(f"No events found for **{tag_names}** on **{label}**.")
    except Exception as e:
        logger.exception(f"Error in /agenda command: {e}")
        await interaction.followup.send("An error occurred while processing the agenda.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🎭 /greet                                                    ║
# ║ Generates a persona-based medieval greeting with image      ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="greet", description="Post the morning greeting with image")
async def greet_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        await post_todays_happenings(bot, include_greeting=True)
        await interaction.followup.send("Greeting and image posted.")
    except Exception as e:
        logger.exception(f"Error in /greet command: {e}")
        await interaction.followup.send("An error occurred while posting the greeting.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔄 /reload                                                   ║
# ║ Reloads calendar sources and user mappings                  ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="reload", description="Reload calendar sources and user mappings")
async def reload_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        # Reload calendars from server configurations
        from events import load_calendars_from_server_configs, reinitialize_events
        load_calendars_from_server_configs()  # Ensure GROUPED_CALENDARS is updated
        await reinitialize_events()  # Reinitialize events for all calendars
        await interaction.followup.send("Reloaded calendar sources and user mappings.")
    except Exception as e:
        logger.exception(f"Error in /reload command: {e}")
        await interaction.followup.send("An error occurred while reloading.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 📇 /who                                                      ║
# ║ Displays all active tags and their mapped display names     ║
# ╚═════════════════════════════════════════════════════════════╝
@bot.tree.command(name="who", description="List all calendars and their assigned users")
async def who_command(interaction: discord.Interaction):
    try:
        await interaction.response.defer()
        lines = [
            f"**User ID: {user_id}** → {', '.join(cal['name'] for cal in calendars)}"
            for user_id, calendars in GROUPED_CALENDARS.items()
        ]
        await interaction.followup.send("**Calendars and Assigned Users:**\n" + "\n".join(lines))
    except Exception as e:
        logger.exception(f"Error in /who command: {e}")
        await interaction.followup.send("An error occurred while listing calendars.")


# ╔═════════════════════════════════════════════════════════════╗
# ║ 🔗 resolve_tag_mappings                                      ║
# ║ Assigns display names and colors to tags based on members   ║
# ╚═════════════════════════════════════════════════════════════╝
async def resolve_tag_mappings():
    """Resolve user mappings and populate display names."""
    from events import GROUPED_CALENDARS

    # Clear existing mappings
    TAG_NAMES.clear()
    TAG_COLORS.clear()

    # Assign display names for user IDs
    resolved_count = 0
    for guild in bot.guilds:
        for member in guild.members:
            if member.id in GROUPED_CALENDARS:
                TAG_NAMES[member.id] = member.display_name
                resolved_count += 1

    logger.info(f"Resolved {resolved_count} user mappings to display names.")


# ╔═════════════════════════════════════════════════════════════════╗
# ║ 📢 send_migration_guidance                                  ║
# ║ Sends guidance messages to server admins about migration    ║
# ╚═════════════════════════════════════════════════════════════╝
async def send_migration_guidance():
    """Send one-time guidance messages to server admins about the configuration migration."""
    # No need to import get_all_server_ids here anymore since we added it to the imports
    
    # Check if we have any configured servers yet
    server_ids = get_all_server_ids()
    
    # Get the creation date of the bot's session file to determine if this is a fresh install
    session_marker = os.path.join(SERVER_CONFIG_DIR, ".migration_notice_sent")
    
    # If we've already sent notices, don't send again
    if os.path.exists(session_marker):
        return
        
    try:
        # For each guild the bot is in
        for guild in bot.guilds:
            # Skip if this server is already configured
            if guild.id in server_ids:
                continue
                
            # Try to find an appropriate channel to send the message to
            target_channel = None
            
            # First look for channels with "admin", "bot", "config" in the name
            admin_channel = next((c for c in guild.text_channels 
                if any(term in c.name.lower() for term in ["admin", "bot", "config", "setup"])), None)
            
            if admin_channel:
                target_channel = admin_channel
            else:
                # Fall back to general channel or the first text channel
                general = next((c for c in guild.text_channels if c.name.lower() == "general"), None)
                if general:
                    target_channel = general
                elif guild.text_channels:
                    # Get the oldest (usually most important) channel
                    target_channel = sorted(guild.text_channels, key=lambda c: c.position)[0]
            
            if target_channel:
                # Check if we have permission to send messages
                permissions = target_channel.permissions_for(guild.me)
                if not permissions.send_messages:
                    logger.warning(f"No permission to send guidance in {guild.name} (ID: {guild.id})")
                    continue
                    
                # Send the migration guidance message
                try:
                    await target_channel.send(
                        "**📢 Important CalendarBot Update!**\n\n"
                        "CalendarBot now uses **server-specific configuration**. This means:\n\n"
                        "• Each server can have its own calendars and user mappings\n"
                        "• Environment variables are no longer used for calendar setup\n"
                        "• Use the `/setup` command to configure your calendars\n\n"
                        "Type `/setup list` to view your current configuration.\n"
                        "Type `/setup add calendar_url:your_calendar_id user:@username` to add a calendar.\n\n"
                        "Need help? Check the documentation for more information."
                    )
                    logger.info(f"Sent migration guidance to server: {guild.name} (ID: {guild.id})")
                except Exception as e:
                    logger.warning(f"Failed to send guidance to {guild.name}: {e}")
        
        # Create marker file to avoid sending notices again
        with open(session_marker, 'w') as f:
            f.write(datetime.now().isoformat())
            
    except Exception as e:
        logger.exception(f"Error in send_migration_guidance: {e}")


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
            cal_type = cal.get("type", "unknown")
            cal_id = cal.get("id", "unknown")
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_tag = cal.get("tag", "No Tag")
            
            # Find the user associated with this tag
            user_id = None
            for tag_key, uid in config.get("user_mappings", {}).items():
                if tag_key == cal_tag:
                    user_id = uid
                    break
                    
            user_mention = f"<@{user_id}>" if user_id else "No user"
            
            # Truncate long calendar IDs
            if len(cal_id) > 30:
                display_id = cal_id[:27] + "..."
            else:
                display_id = cal_id
                
            lines.append(f"{i}. **{cal_name}** ({cal_type})\n   ID: `{display_id}`\n   User: {user_mention}\n   Tag: `{cal_tag}`")
        
        # Add service account info for Google Calendar sharing
        service_email = get_service_account_email()
        lines.append(f"\n**Google Calendar Service Account:**\n`{service_email}`")
        
        await interaction.followup.send("\n".join(lines), ephemeral=True)


class AddCalendarModal(Modal, title="Add Calendar"):
    """Modal form for adding a new calendar."""
    
    # Text inputs for the form
    calendar_url = TextInput(
        label="Calendar URL or ID",
        placeholder="Google Calendar ID or ICS URL",
        required=True,
        style=discord.TextStyle.short
    )
    
    display_name = TextInput(
        label="Calendar Display Name (Optional)",
        placeholder="e.g. 'Work Calendar' or 'Family Events'",
        required=False,
        style=discord.TextStyle.short
    )
    
    def __init__(self, bot, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle the form submission."""
        await interaction.response.defer(ephemeral=True)
        
        # Step 1: Validate the calendar URL
        calendar_url = self.calendar_url.value.strip()
        
        # Detect calendar type
        calendar_type = detect_calendar_type(calendar_url)
        if not calendar_type:
            await interaction.followup.send(
                "❌ Invalid calendar format. Please provide a valid Google Calendar ID or ICS URL.", 
                ephemeral=True
            )
            return
            
        # Step 2: Show user selection view
        # Create a select menu with guild members
        view = UserSelectView(self.bot, self.guild_id, calendar_url, self.display_name.value)
        
        if calendar_type == 'google':
            instructions = (
                f"**Google Calendar Detected**\n\n"
                f"After selecting a user, you'll need to share your Google Calendar with:\n"
                f"`{get_service_account_email()}`\n\n"
                f"**Select which user this calendar belongs to:**"
            )
        else:
            instructions = "**ICS Calendar Detected**\n\n**Select which user this calendar belongs to:**"
            
        await interaction.followup.send(instructions, view=view, ephemeral=True)


class UserSelectView(View):
    """View for selecting which user the calendar belongs to."""
    def __init__(self, bot, guild_id, calendar_url, display_name):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_url = calendar_url
        self.display_name = display_name
        
        # Create select menu with guild members
        self.add_item(self.create_user_select())
        
    def create_user_select(self):
        """Create a select menu with server members."""
        # Get guild
        guild = self.bot.get_guild(self.guild_id)
        
        # Create select with members (limit to 25 options)
        select = Select(
            placeholder="Select a user...",
            min_values=1,
            max_values=1
        )
        
        # Sort members by name for easier selection
        sorted_members = sorted(
            [m for m in guild.members if not m.bot],
            key=lambda m: m.display_name.lower()
        )
        
        # Take first 25 (Discord limit) - in a real app you might need pagination
        for member in sorted_members[:25]:
            select.add_option(
                label=member.display_name,
                value=str(member.id),
                description=f"User ID: {member.id}"
            )
            
        select.add_option(
            label="@everyone",
            value="EVERYONE",
            description="Assign this calendar to all server members"
        )
            
        async def select_callback(interaction):
            """Handle user selection."""
            if select.values[0] == "EVERYONE":
                user_id = "EVERYONE"
                user = None
            else:
                user_id = select.values[0]
                user = guild.get_member(int(user_id))
            
            # If display name wasn't provided, use user's name + "Calendar"
            final_display_name = self.display_name
            if not final_display_name and user_id == "EVERYONE":
                final_display_name = "Everyone's Calendar"
            elif not final_display_name:
                final_display_name = f"{user.display_name}'s Calendar"
                
            # Add the calendar
            success, message = add_calendar(
                self.guild_id,
                self.calendar_url,
                user_id,
                final_display_name
            )
            
            # Reload calendar configuration and reinitialize events
            from events import reinitialize_events
            asyncio.create_task(reinitialize_events())
            
            # Show the result
            await interaction.response.send_message(
                f"{'✅' if success else '❌'} {message}",
                ephemeral=True
            )
            
        select.callback = select_callback
        return select


class CalendarRemoveView(View):
    """View for selecting which calendar to remove."""
    def __init__(self, bot, guild_id, calendars):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.guild_id = guild_id
        
        # Create select menu with calendars
        select = Select(
            placeholder="Select calendar to remove...",
            min_values=1,
            max_values=1
        )
        
        # Add each calendar as an option
        for i, cal in enumerate(calendars):
            cal_name = cal.get("name", "Unnamed Calendar")
            cal_id = cal.get("id", "unknown")
            
            # Truncate long IDs for display
            if len(cal_id) > 30:
                display_id = cal_id[:20] + "..." + cal_id[-7:]
            else:
                display_id = cal_id
                
            select.add_option(
                label=cal_name[:80] if len(cal_name) > 80 else cal_name,
                value=cal_id[:100] if len(cal_id) > 100 else cal_id,
                description=f"ID: {display_id}"
            )
            
        async def select_callback(interaction):
            """Handle calendar selection for removal."""
            calendar_id = select.values[0]
            
            # Add confirmation button
            confirm_view = ConfirmRemovalView(self.bot, self.guild_id, calendar_id)
            await interaction.response.send_message(
                f"Are you sure you want to remove this calendar?\n`{calendar_id}`",
                view=confirm_view,
                ephemeral=True
            )
            
        select.callback = select_callback
        self.add_item(select)


class ConfirmRemovalView(View):
    """Confirmation view for calendar removal."""
    def __init__(self, bot, guild_id, calendar_id):
        super().__init__(timeout=60)  # Short timeout for confirmation
        self.bot = bot
        self.guild_id = guild_id
        self.calendar_id = calendar_id
        
    @discord.ui.button(label="Confirm Removal", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Remove the calendar when confirmed."""
        # Remove the calendar
        success, message = remove_calendar(self.guild_id, self.calendar_id)
        
        # Reload calendar configuration if successful and reinitialize events
        if success:
            from events import reinitialize_events
            asyncio.create_task(reinitialize_events())
            
        await interaction.response.send_message(
            f"{'✅' if success else '❌'} {message}",
            ephemeral=True
        )
        
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Cancel the removal."""
        await interaction.response.send_message("Calendar removal cancelled.", ephemeral=True)
        self.stop()


# ╔═════════════════════════════════════════════════════════════════╗
# ║ ⚙️ /setup                                                       ║
# ║ Command to interactively configure server calendars             ║
# ╚═════════════════════════════════════════════════════════════════╝
@bot.tree.command(
    name="setup",
    description="Configure calendars for the server with guided setup"
)
async def setup_command(interaction: discord.Interaction):
    """Interactive calendar setup command."""
    try:
        # Check for admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⚠️ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return
        
        # Start the guided setup process
        view = CalendarSetupView(bot, interaction.guild_id)
        
        await interaction.response.send_message(
            "# 📅 Calendar Setup Wizard\n\n"
            "Welcome to the guided setup process! What would you like to do?\n\n"
            "• **Add Calendar**: Connect a Google Calendar or ICS feed\n"
            "• **Remove Calendar**: Delete a configured calendar\n"
            "• **List Calendars**: View currently configured calendars\n\n"
            "Choose an option below to continue:",
            view=view,
            ephemeral=True
        )
            
    except Exception as e:
        logger.exception(f"Error in setup command: {e}")
        await interaction.response.send_message(
            f"An error occurred during setup: {str(e)}", 
            ephemeral=True
        )
