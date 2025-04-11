"""
commands.py: Implements the slash commands for greeting, heralding, and agendas,
plus utilities for sending embeds to a predefined announcement channel.
"""

import os
import asyncio
import random
import dateparser
from datetime import datetime, timedelta, date
import discord
from discord import Interaction, app_commands
from discord.errors import Forbidden, HTTPException, GatewayNotFound
from collections import defaultdict
from typing import List

from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    TAG_NAMES
)
from utils import format_event, validate_env_vars, format_message_lines
from log import logger
from ai import generate_greeting, generate_image
from views import CalendarSetupView


# Add validation for critical environment variables
validate_env_vars(["ANNOUNCEMENT_CHANNEL_ID", "DISCORD_BOT_TOKEN"])

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 Autocomplete Functions                                          ║
# ║ Provides suggestions for command arguments                         ║
# ╚════════════════════════════════════════════════════════════════════╝
async def autocomplete_tag(
    interaction: discord.Interaction, 
    current: str
) -> List[app_commands.Choice[str]]:
    """
    Provides autocomplete suggestions for user IDs.
    Used by commands that need to filter by user.
    """
    suggestions = []
    
    # Add all user IDs
    for user_id in GROUPED_CALENDARS:
        suggestions.append((user_id, user_id))
    
    # Filter based on current input
    if current:
        filtered = [
            app_commands.Choice(name=user_id, value=user_id)
            for user_id in suggestions 
            if current.lower() in user_id.lower()
        ]
        return filtered[:25]  # Discord limits to 25 choices
    
    # Return all suggestions if no input
    return [app_commands.Choice(name=user_id, value=user_id) for user_id in suggestions[:25]]

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 _retry_discord_operation                                        ║
# ║ Helper function to retry Discord API operations with backoff      ║
# ╚════════════════════════════════════════════════════════════════════╝
async def _retry_discord_operation(operation, max_retries=3):
    last_error = None
    
    for attempt in range(max_retries):
        try:
            return await operation()
        except Forbidden as e:
            # Permission errors should not be retried
            logger.error(f"Permission error during Discord operation: {e}")
            raise
        except (HTTPException, GatewayNotFound) as e:
            backoff = (2 ** attempt) + random.random()
            logger.warning(f"Discord API error (attempt {attempt+1}/{max_retries}): {e}")
            logger.info(f"Retrying in {backoff:.2f} seconds...")
            last_error = e
            await asyncio.sleep(backoff)
    
    # If we've exhausted all retries, raise the last error
    if last_error:
        raise last_error


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 check_channel_permissions                                        ║
# ║ Verifies the bot has necessary permissions in the channel          ║
# ╚════════════════════════════════════════════════════════════════════╝
def check_channel_permissions(channel, bot_member):
    required_permissions = [
        "view_channel",
        "send_messages",
        "embed_links",
        "attach_files"
    ]
    
    missing = []
    permissions = channel.permissions_for(bot_member)
    
    for perm in required_permissions:
        if not getattr(permissions, perm, False):
            missing.append(perm)
    
    return not missing, missing


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📤 send_embed                                                      ║
# ║ Sends an embed to the announcement channel, optionally with image ║
# ╚════════════════════════════════════════════════════════════════════╝
async def send_embed(bot, embed: discord.Embed = None, title: str = "", description: str = "", color: int = 5814783, image_path: str | None = None, content: str = ""):
    try:
        if isinstance(embed, str):
            logger.warning("send_embed() received a string instead of an Embed. Converting values assuming misuse.")
            description = embed
            embed = None
            
        from environ import ANNOUNCEMENT_CHANNEL_ID
        if not ANNOUNCEMENT_CHANNEL_ID:
            logger.warning("ANNOUNCEMENT_CHANNEL_ID not set.")
            return
            
        # Get channel with retry
        channel = None
        for _ in range(2):  # Try twice in case of cache issues
            channel = bot.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                break
            # If not found in cache, try to fetch it
            try:
                channel = await bot.fetch_channel(ANNOUNCEMENT_CHANNEL_ID)
                break
            except Exception as e:
                logger.warning(f"Error fetching channel: {e}")
                await asyncio.sleep(1)
        
        if not channel:
            logger.error("Channel not found. Check ANNOUNCEMENT_CHANNEL_ID.")
            return
            
        # Check permissions
        bot_member = channel.guild.get_member(bot.user.id)
        has_permissions, missing_perms = check_channel_permissions(channel, bot_member)
        
        if not has_permissions:
            logger.error(f"Missing permissions in channel {channel.name}: {', '.join(missing_perms)}")
            return
            
        # Create embed if none was provided
        if embed is None:
            embed = discord.Embed(title=title, description=description, color=color)
            
        # Check if embed is too large (Discord limit is 6000 characters)
        embed_size = len(embed.title) + len(embed.description or "")
        for field in embed.fields:
            embed_size += len(field.name) + len(field.value)
            
        if embed_size > 5900:  # Leave some buffer
            logger.warning(f"Embed exceeds Discord's size limit ({embed_size}/6000 chars). Splitting content.")
            
            # Create a new embed with just title and description
            main_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
            if embed.footer:
                main_embed.set_footer(text=embed.footer.text)
                
            # Send the main embed first
            await _retry_discord_operation(lambda: channel.send(content=content, embed=main_embed))
            
            # Then send fields as separate embeds, grouping a few fields per embed
            field_groups = []
            current_group = []
            current_size = 0
            
            for field in embed.fields:
                field_size = len(field.name) + len(field.value)
                if current_size + field_size > 4000:  # Conservative field size limit
                    field_groups.append(current_group)
                    current_group = [field]
                    current_size = field_size
                else:
                    current_group.append(field)
                    current_size += field_size
                    
            if current_group:
                field_groups.append(current_group)
                
            for i, group in enumerate(field_groups):
                continuation_embed = discord.Embed(color=embed.color)
                if i < len(field_groups) - 1:
                    continuation_embed.set_footer(text=f"Continued ({i+1}/{len(field_groups)})")
                else:
                    if embed.footer:
                        continuation_embed.set_footer(text=embed.footer.text)
                        
                for field in group:
                    continuation_embed.add_field(name=field.name, value=field.value, inline=field.inline)
                    
                await _retry_discord_operation(lambda: channel.send(content=content, embed=continuation_embed))
                
            return
            
        # Process image if provided
        file = None
        if image_path and os.path.exists(image_path):
            try:
                file = discord.File(image_path, filename="image.png")
                embed.set_image(url="attachment://image.png")
            except Exception as e:
                logger.warning(f"Failed to load image from {image_path}: {e}")
                # Continue without the image
        
        # Send the message with retry
        if file:
            await _retry_discord_operation(lambda: channel.send(content=content, embed=embed, file=file))
        else:
            await _retry_discord_operation(lambda: channel.send(content=content, embed=embed))
            
    except Exception as e:
        logger.exception(f"Error in send_embed: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📅 post_tagged_events                                              ║
# ║ Sends an embed of events for a specific tag on a given day        ║
# ║ Returns True if events were posted, False otherwise               ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_events(interaction: discord.Interaction, day: datetime.date) -> bool:
    try:
        user_id = str(interaction.user.id)
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            logger.warning(f"No calendars found for user ID: {user_id}")
            await interaction.followup.send("No calendars found for your account.", ephemeral=True)
            return False

        events_by_source = defaultdict(list)
        for meta in calendars:
            try:
                events = get_events(meta, day, day)
                if not events:
                    events = []
                for e in events:
                    events_by_source[meta["name"]].append(e)
            except Exception as e:
                logger.exception(f"Error getting events for {meta['name']}: {e}")

        if not events_by_source:
            logger.debug(f"Skipping {user_id} — no events for {day}")
            await interaction.followup.send(f"No events found for {day.strftime('%A, %B %d')}.", ephemeral=True)
            return False

        # Construct formatted message
        message_lines = [f"🗓️ **Today's Events for {interaction.user.mention} — {day.strftime('%A, %B %d')}**\n"]
        for source_name, events in sorted(events_by_source.items()):
            if not events:
                continue
            message_lines.append(f"**{source_name}**")
            for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                start_time = e["start"].get("dateTime", e["start"].get("date"))
                end_time = e["end"].get("dateTime", e["end"].get("date"))
                summary = e.get("summary", "No Title")
                location = e.get("location", "No Location")
                message_lines.append(
                    f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```"
                )

        # Send the message as an ephemeral response
        await interaction.followup.send("\n".join(message_lines), ephemeral=True)
        return True

    except Exception as e:
        logger.exception(f"Error in post_tagged_events for user ID {user_id} on {day}: {e}")
        await interaction.followup.send("⚠️ An error occurred while fetching events.", ephemeral=True)
        return False


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /herald [tag] — Posts today's events for a calendar tag
# ╚════════════════════════════════════════════════════════════════════╝
async def post_tagged_week(interaction: discord.Interaction, monday: datetime.date):
    try:
        user_id = str(interaction.user.id)
        events_by_day = defaultdict(list)
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            logger.warning(f"No calendars found for user ID: {user_id}")
            await interaction.followup.send("No calendars found for your account.", ephemeral=True)
            return

        for meta in calendars:
            try:
                events = get_events(meta, monday, monday + timedelta(days=6))
                for e in events or []:
                    start_date = datetime.fromisoformat(e["start"].get("dateTime", e["start"].get("date"))).date()
                    events_by_day[start_date].append(e)
            except Exception as e:
                logger.exception(f"Error getting events for calendar {meta['name']}: {e}")

        if not events_by_day:
            logger.debug(f"Skipping {user_id} — no events for the week starting {monday}")
            await interaction.followup.send(f"No events found for the week starting {monday.strftime('%A, %B %d')}.", ephemeral=True)
            return

        # Use helper function for formatting
        message_lines = format_message_lines(user_id, events_by_day, monday)
        await interaction.followup.send("\n".join(message_lines), ephemeral=True)

    except Exception as e:
        logger.exception(f"Error in post_tagged_week for user ID {user_id}: {e}")
        await interaction.followup.send("⚠️ An error occurred while fetching weekly events.", ephemeral=True)


# Define or import reload_calendars_and_mappings
async def reload_calendars_and_mappings():
    """Reload calendar sources and user mappings."""
    from events import load_calendars_from_server_configs, reinitialize_events
    load_calendars_from_server_configs()
    await reinitialize_events()


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /agenda [date] — Returns events for a specific date
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_agenda_command(interaction: discord.Interaction, date: str):
    """Handles the logic for the /agenda command."""
    await interaction.response.defer(ephemeral=True)
    logger.info(f"[commands.py] 📅 /agenda called by {interaction.user} with date '{date}'")

    try:
        dt = dateparser.parse(date)
        if not dt:
            await interaction.followup.send("⚠️ Could not understand that date.", ephemeral=True)
            return

        day = dt.date()
        all_events = []
        for user_id, sources in GROUPED_CALENDARS.items():
            for source in sources:
                events = await interaction.client.loop.run_in_executor(None, get_events, source, day, day)
                all_events.extend(events)

        # Sort by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date")))

        if not all_events:
            await interaction.followup.send(f"No events found for `{date}`.", ephemeral=True)
            return

        # Construct plain text message
        message_lines = [f"🗓️ **Agenda for {interaction.user.display_name} on {day.strftime('%A, %d %B %Y')}**"]
        for e in all_events:
            message_lines.append(f" {format_event(e)}")

        # Send the message as an ephemeral response
        await interaction.followup.send("\n".join(message_lines), ephemeral=True)

    except Exception as e:
        logger.exception("[commands.py] Error in /agenda command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while fetching the agenda.", ephemeral=True)


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /greet — Posts the morning greeting with image
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_greet_command(interaction: discord.Interaction):
    """Handles the logic for the /greet command."""
    await interaction.response.defer()
    logger.info(f"[commands.py] 📅 /greet called by {interaction.user}")

    try:
        greeting = await generate_greeting()
        image_path = await generate_image(greeting)

        embed = discord.Embed(description=greeting, color=5814783)
        if image_path:
            file = discord.File(image_path, filename="greeting.png")
            embed.set_image(url="attachment://greeting.png")
            await interaction.followup.send(embed=embed, file=file)
        else:
            await interaction.followup.send(embed=embed)

    except Exception as e:
        logger.exception("[commands.py] Error in /greet command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while posting the greeting.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /reload — Reloads calendar sources and user mappings
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_reload_command(interaction: discord.Interaction):
    """Handles the logic for the /reload command."""
    await interaction.response.defer()
    logger.info(f"[commands.py] 📅 /reload called by {interaction.user}")

    try:
        # Reload calendar sources and user mappings
        # Assuming you have a function to reload these
        await reload_calendars_and_mappings()
        await interaction.followup.send("✅ Calendar sources and user mappings reloaded.")

    except Exception as e:
        logger.exception("[commands.py] Error in /reload command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while reloading calendar sources and user mappings.")


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /who — Lists all calendars and their assigned users
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_who_command(interaction: discord.Interaction):
    """Handles the logic for the /who command."""
    await interaction.response.defer(ephemeral=True)
    logger.info(f"[commands.py] 📅 /who called by {interaction.user}")

    try:
        message_lines = ["📅 **Calendars and Assigned Users**"]
        for user_id, sources in GROUPED_CALENDARS.items():
            user_name = TAG_NAMES.get(user_id, "User")
            message_lines.append(f"**{user_name}** ({user_id})")
            for source in sources:
                message_lines.append(f" - {source['name']}")

        await interaction.followup.send("\n".join(message_lines), ephemeral=True)

    except Exception as e:
        logger.exception("[commands.py] Error in /who command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while listing calendars and users.", ephemeral=True)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📢 post_daily_events_to_channel                                    ║
# ║ Posts a user's daily events to the announcement channel            ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_daily_events_to_channel(bot, user_id: str, day: datetime.date) -> bool:
    """Posts a user's daily events to the announcement channel instead of DMs."""
    try:
        calendars = GROUPED_CALENDARS.get(user_id)
        if not calendars:
            logger.warning(f"No calendars found for user ID: {user_id}")
            return False

        events_by_source = defaultdict(list)
        for meta in calendars:
            try:
                events = get_events(meta, day, day)
                if not events:
                    events = []
                for e in events:
                    events_by_source[meta["name"]].append(e)
            except Exception as e:
                logger.exception(f"Error getting events for {meta['name']}: {e}")

        if not events_by_source:
            logger.debug(f"Skipping {user_id} — no events for {day}")
            return False

        # Construct formatted message with user mention
        user_mention = f"<@{user_id}>"
        user_name = TAG_NAMES.get(user_id, "User")
        
        message_lines = [f"🗓️ **Today's Events for {user_mention} — {day.strftime('%A, %B %d')}**\n"]
        for source_name, events in sorted(events_by_source.items()):
            if not events:
                continue
            message_lines.append(f"**{source_name}**")
            for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                start_time = e["start"].get("dateTime", e["start"].get("date"))
                end_time = e["end"].get("dateTime", e["end"].get("date"))
                summary = e.get("summary", "No Title")
                
                # Process summary to replace potential user references with mentions
                for uid, name in TAG_NAMES.items():
                    if name in summary:
                        summary = summary.replace(f"@{name}", f"<@{uid}>")
                        summary = summary.replace(name, f"<@{uid}>")
                
                location = e.get("location", "No Location")
                message_lines.append(
                    f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```"
                )

        # Send the message to the announcement channel
        embed = discord.Embed(
            description="\n".join(message_lines),
            color=get_color_for_tag(user_id) if callable(get_color_for_tag) else 5814783
        )
        await send_embed(bot, embed=embed)
        return True

    except Exception as e:
        logger.exception(f"Error in post_daily_events_to_channel for user ID {user_id} on {day}: {e}")
        return False


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📢 post_all_daily_events_to_channel                               ║
# ║ Posts all users' daily events to the announcement channel         ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_all_daily_events_to_channel(bot, day: datetime.date = None):
    """Posts all users' daily events to the announcement channel."""
    if day is None:
        day = get_today()
    
    try:
        messages_sent = 0
        for user_id in GROUPED_CALENDARS:
            if await post_daily_events_to_channel(bot, user_id, day):
                messages_sent += 1
        
        return messages_sent
    except Exception as e:
        logger.exception(f"Error in post_all_daily_events_to_channel: {e}")
        return 0


# ╔════════════════════════════════════════════════════════════════════╗
# 📅 /daily — Manually posts today's events for all users to the channel
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_daily_command(interaction: discord.Interaction):
    """Handles the logic for the /daily command."""
    await interaction.response.defer()
    logger.info(f"[commands.py] 📅 /daily called by {interaction.user} in guild {interaction.guild.name} (ID: {interaction.guild.id})")

    from environ import ANNOUNCEMENT_CHANNEL_ID
    if not ANNOUNCEMENT_CHANNEL_ID:
        await interaction.followup.send("⚠️ Announcement channel is not configured.", ephemeral=True)
        return

    try:
        day = get_today()
        messages_sent = await post_all_daily_events_to_channel(interaction.client, day)

        if messages_sent > 0:
            await interaction.followup.send(f"Posted daily events for {messages_sent} users to the announcement channel.", ephemeral=True)
        else:
            await interaction.followup.send("No events found for today.", ephemeral=True)

    except Exception as e:
        logger.exception("[commands.py] Error in /daily command.", exc_info=e)
        await interaction.followup.send("⚠️ An error occurred while posting daily events.", ephemeral=True)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⚙️ /setup                                                          ║
# ║ Command to interactively configure server calendars                ║
# ╚════════════════════════════════════════════════════════════════════╝
async def handle_setup_command(interaction: discord.Interaction):
    """Handles the logic for the /setup command."""
    try:
        # Check for admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "⚠️ You need administrator permissions to use this command.", 
                ephemeral=True
            )
            return
        
        # Start the guided setup process
        view = CalendarSetupView(interaction.client, interaction.guild_id)
        
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

async def handle_herald_command(interaction: Interaction):
    """Handles the logic for the /herald command."""
    await interaction.response.defer(ephemeral=True)
    logger.info(f"[commands.py] 📅 /herald called by {interaction.user}")
    try:
        today = get_today()
        monday = get_monday_of_week(today)
        
        weekly_message_parts = []
        daily_message_parts = []
        errors = []  # Track errors for partial failures
        
        # Collect weekly data for all users
        for user_id in GROUPED_CALENDARS:
            try:
                user_name = TAG_NAMES.get(user_id, "Unknown User")
                user_mention = f"<@{user_id}>"
                
                # Get weekly events for this user
                events_by_day = defaultdict(list)
                calendars = GROUPED_CALENDARS.get(user_id)
                
                if not calendars:
                    continue
                    
                for meta in calendars:
                    try:
                        events = get_events(meta, monday, monday + timedelta(days=6))
                        if not events:
                            continue
                        for e in events:
                            start_date = datetime.fromisoformat(e["start"].get("dateTime", e["start"].get("date"))).date()
                            events_by_day[start_date].append(e)
                    except Exception as e:
                        logger.warning(f"Error getting events for calendar {meta['name']} (user {user_id}): {e}")
                
                if not events_by_day:
                    continue
                    
                # Add section for this user's weekly events
                user_weekly = [f"\n## 📆 **{user_mention}'s Weekly Events**\n"]
                
                for i in range(7):
                    day = monday + timedelta(days=i)
                    day_events = events_by_day.get(day, [])
                    if not day_events:
                        continue
                        
                    user_weekly.append(f"### 📅 **{day.strftime('%A, %B %d')}**")
                    for e in sorted(day_events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                        start_time = e["start"].get("dateTime", e["start"].get("date"))
                        end_time = e["end"].get("dateTime", e["end"].get("date"))
                        summary = e.get("summary", "No Title")
                        location = e.get("location", "No Location")
                        
                        # Process mentions in event summary
                        for uid, name in TAG_NAMES.items():
                            if name in summary:
                                summary = summary.replace(f"@{name}", f"<@{uid}>")
                                summary = summary.replace(name, f"<@{uid}>")
                        
                        user_weekly.append(f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```")
                
                weekly_message_parts.append("\n".join(user_weekly))
                
                # Get daily events for this user
                events_by_source = defaultdict(list)
                for meta in calendars:
                    try:
                        events = get_events(meta, today, today)
                        if not events:
                            continue
                        for e in events:
                            events_by_source[meta["name"]].append(e)
                    except Exception as e:
                        logger.warning(f"Error getting events for {meta['name']} (user {user_id}): {e}")
                
                if not events_by_source:
                    continue
                    
                # Add section for this user's daily events
                user_daily = [f"\n## 🗓️ **{user_mention}'s Events Today ({today.strftime('%A, %B %d')})**\n"]
                
                for source_name, events in sorted(events_by_source.items()):
                    if not events:
                        continue
                    user_daily.append(f"**{source_name}**")
                    for e in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                        start_time = e["start"].get("dateTime", e["start"].get("date"))
                        end_time = e["end"].get("dateTime", e["end"].get("date"))
                        summary = e.get("summary", "No Title")
                        
                        # Process mentions in event summary
                        for uid, name in TAG_NAMES.items():
                            if name in summary:
                                summary = summary.replace(f"@{name}", f"<@{uid}>")
                                summary = summary.replace(name, f"<@{uid}>")
                        
                        location = e.get("location", "No Location")
                        user_daily.append(f"```{summary}\nTime: {start_time} - {end_time}\nLocation: {location}```")
                
                daily_message_parts.append("\n".join(user_daily))
            except Exception as e:
                logger.error(f"Error processing user {user_id}: {e}")
                errors.append(f"User {user_id}: {e}")
        
        # Combine and send all weekly messages first
        if weekly_message_parts:
            weekly_header = "# 📜 **Weekly Events Summary**\n"
            weekly_chunks = [weekly_header]
            current_chunk = weekly_header
            
            for part in weekly_message_parts:
                if len(current_chunk) + len(part) > 1900:
                    weekly_chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += part
            
            if current_chunk != weekly_header:
                weekly_chunks.append(current_chunk)
            
            # Send all weekly chunks
            for chunk in weekly_chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)  # Send as ephemeral messages
        
        # Then send all daily messages
        if daily_message_parts:
            daily_header = "# 🗓️ **Today's Events Summary**\n"
            daily_chunks = [daily_header]
            current_chunk = daily_header
            
            for part in daily_message_parts:
                if len(current_chunk) + len(part) > 1900:
                    daily_chunks.append(current_chunk)
                    current_chunk = part
                else:
                    current_chunk += part
            
            if current_chunk != daily_header:
                daily_chunks.append(current_chunk)
            
            # Send all daily chunks
            for chunk in daily_chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)  # Send as ephemeral messages
        
        # Report errors if any
        if errors:
            error_message = "\n".join(errors)
            await interaction.followup.send(
                f"⚠️ Some errors occurred while processing:\n```{error_message}```",
                ephemeral=True
            )
        
        # Confirmation message
        await interaction.followup.send("Herald events for all users have been sent.", ephemeral=True)
    except Exception as e:
        logger.exception(f"Error in /herald command: {e}")
        await interaction.followup.send("An error occurred while posting the herald.", ephemeral=True)

def get_today() -> date:
    """Returns the current date."""
    return date.today()

def get_monday_of_week(day: date) -> date:
    """Returns the Monday of the week for the given date."""
    return day - timedelta(days=day.weekday())
