from datetime import date, timedelta, datetime
from typing import Optional
import discord
from discord import Interaction
from collections import defaultdict
import asyncio

from bot.events import GROUPED_CALENDARS, TAG_NAMES, get_events
from utils import format_message_lines, get_today, get_monday_of_week, format_event
from .utilities import _retry_discord_operation, check_channel_permissions, send_embed
from utils.logging import logger

# Herald command implementations
async def post_tagged_events(interaction: Interaction, day: date):
    try:
        user_id = str(interaction.user.id)
        calendars = GROUPED_CALENDARS.get(user_id)
        
        if not calendars:
            await interaction.followup.send("No calendars configured", ephemeral=True)
            return False

        events_by_source = defaultdict(list)
        for meta in calendars:
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, day, day)
            events_by_source[meta['name']].extend(events or [])

        if not events_by_source:
            await interaction.followup.send(f"No events for {day.strftime('%Y-%m-%d')}", ephemeral=True)
            return False

        message = format_message_lines(user_id, events_by_source, day)
        await interaction.followup.send(message, ephemeral=True)
        return True
    except Exception as e:
        logger.error(f"Herald error: {e}")
        await interaction.followup.send("Failed to retrieve events", ephemeral=True)
        return False

async def post_tagged_week(interaction: Interaction, monday: date):
    try:
        user_id = str(interaction.user.id)
        events_by_day = defaultdict(list)
        
        for meta in GROUPED_CALENDARS.get(user_id, []):
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, monday, monday + timedelta(days=6))
            for e in events or []:
                start_date = datetime.fromisoformat(e['start'].get('dateTime', e['start'].get('date'))).date()
                events_by_day[start_date].append(e)

        if not events_by_day:
            await interaction.followup.send("No weekly events found", ephemeral=True)
            return

        message = format_message_lines(user_id, events_by_day, monday)
        await interaction.followup.send(message, ephemeral=True)
    except Exception as e:
        logger.error(f"Weekly herald error: {e}")
        await interaction.followup.send("Failed to retrieve weekly schedule", ephemeral=True)

async def handle_herald_command(interaction: Interaction):
    """Main handler for the herald command that shows all events for the day and week"""
    await interaction.response.defer(ephemeral=True)  # Make sure defer is also ephemeral
    try:
        today = get_today()
        monday = get_monday_of_week(today)
        
        # Check if user has any calendars
        user_id = str(interaction.user.id)
        if user_id not in GROUPED_CALENDARS:
            await interaction.followup.send("⚠️ No calendars are configured for you. Please contact an admin to set up your calendars.", ephemeral=True)
            return
        
        # Create user mention
        user_mention = f"<@{user_id}>"
        
        # Create embeds for better visual presentation
        embed_today = discord.Embed(
            title=f"📅 Today's Events • {today.strftime('%A, %B %d')}",
            color=0x3498db,
            description=f"Events for {user_mention} on {today.strftime('%A, %B %d')}"
        )
        embed_today.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        embed_week = discord.Embed(
            title=f"📆 Weekly Schedule • Week of {monday.strftime('%B %d')}",
            color=0x9b59b6,
            description=f"Upcoming schedule for {user_mention}"
        )
        embed_week.set_footer(text=f"Requested by {interaction.user.display_name}")
        
        # Get daily events
        daily_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, today, today)
            for event in events or []:
                daily_events[meta['name']].extend([event])
        
        # Add daily events to embed
        if not daily_events:
            embed_today.add_field(
                name="No Events Today",
                value="You have no scheduled events for today.",
                inline=False
            )
            await interaction.followup.send(embed=embed_today, ephemeral=True)
        else:
            # Format the daily events for the embed
            for calendar_name, events in sorted(daily_events.items()):
                if events:
                    # Create a list of formatted events for this calendar
                    formatted_events = []
                    for event in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                        formatted_event = format_event(event)
                        formatted_events.append(formatted_event)
                    
                    # Join all events for this calendar with newlines
                    events_text = "\n".join(formatted_events)
                    if len(events_text) > 1024:  # Discord field value limit
                        events_text = events_text[:1021] + "..."
                    
                    embed_today.add_field(
                        name=f"📁 {calendar_name}",
                        value=events_text or "*No events*",
                        inline=False
                    )
            
            # Send the daily events embed
            await interaction.followup.send(embed=embed_today, ephemeral=True)
        
        # Get weekly events
        weekly_events = defaultdict(list)
        for meta in GROUPED_CALENDARS[user_id]:
            # Convert synchronous get_events into an awaitable using to_thread
            events = await asyncio.to_thread(get_events, meta, monday, monday + timedelta(days=6))
            for event in events or []:
                start_date = datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date'))).date()
                weekly_events[start_date].append(event)
        
        # Add weekly events to embed
        if not weekly_events:
            embed_week.add_field(
                name="No Events This Week",
                value="You have no scheduled events for this week.",
                inline=False
            )
            await interaction.followup.send(embed=embed_week, ephemeral=True)
        else:
            # Format the weekly events for the embed
            for day, events in sorted(weekly_events.items()):
                # Skip today's events since they're already shown
                if day == today:
                    continue
                
                # Create a list of formatted events for this day
                formatted_events = []
                for event in sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date"))):
                    formatted_event = format_event(event)
                    formatted_events.append(formatted_event)
                
                # Join all events for this day with newlines
                events_text = "\n".join(formatted_events)
                if len(events_text) > 1024:  # Discord field value limit
                    events_text = events_text[:1021] + "..."
                
                embed_week.add_field(
                    name=f"📆 {day.strftime('%A, %B %d')}",
                    value=events_text or "*No events scheduled*",
                    inline=False
                )
            
            # Send the weekly events embed
            await interaction.followup.send(embed=embed_week, ephemeral=True)
            
    except Exception as e:
        logger.exception(f"Herald command error: {e}")
        await interaction.followup.send("⚠️ Failed to retrieve your events", ephemeral=True)

async def register(bot: discord.Client):
    @bot.tree.command(name="herald")
    async def herald_command(interaction: discord.Interaction):
        """Post today's and weekly events from your calendars"""
        await handle_herald_command(interaction)
