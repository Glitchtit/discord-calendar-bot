from datetime import date
import discord
import asyncio
from discord import Interaction
from bot.events import GROUPED_CALENDARS, get_events
from .utilities import send_embed
from utils.logging import logger
from utils import format_message_lines

async def post_daily_events(bot, user_id: str, day: date, interaction_channel=None):
    try:
        sources = GROUPED_CALENDARS.get(user_id, [])
        if not sources:
            return False
        
        events = []
        for meta in sources:
            # Fix: Run get_events in a separate thread since it's synchronous
            events.extend(await asyncio.to_thread(get_events, meta, day, day))
        
        if not events:
            return False
            
        # Fix: Create a dictionary with day as the key and events as the value
        events_by_day = {day: events}
            
        message_lines = format_message_lines(user_id, events_by_day, day)
        
        # Add a check to make sure we're not sending an empty message
        if not message_lines:
            message = f"No events to display for <@{user_id}> on {day.strftime('%A, %B %d')}."
        else:
            # Join the list of message lines into a single string
            message = '\n'.join(message_lines)
        
        # Create a fallback content string that will ensure the message isn't empty
        content = f"Calendar update for <@{user_id}>"
            
        # Try directly accessing the channel and sending the message
        try:
            # Find announcement channel from server configs
            from config.server_config import get_all_server_ids, load_server_config
            
            # Create the embed
            embed = discord.Embed(
                title=f"📅 Calendar Events for {day.strftime('%A, %B %d')}",
                description=message,
                color=0x3498db  # Blue color
            )
            
            channel_found = False
            
            # First try to find the channel from server configs
            server_ids = get_all_server_ids()
            logger.info(f"Checking {len(server_ids)} servers for announcement channels")
            
            for server_id in server_ids:
                config = load_server_config(server_id)
                if config and config.get("announcement_channel_id"):
                    channel_id = int(config.get("announcement_channel_id"))
                    channel = bot.get_channel(channel_id)
                    if channel:
                        logger.info(f"Found announcement channel: {channel.name} (ID: {channel_id})")
                        await channel.send(content=content, embed=embed)
                        logger.info(f"Sent calendar update to channel {channel.name}")
                        channel_found = True
                        return True
                else:
                    logger.debug(f"Server {server_id} has no announcement_channel_id configured")
            
            # If no channel found from configs, try the interaction channel as fallback
            if not channel_found and interaction_channel:
                logger.info(f"Using interaction channel as fallback: {interaction_channel.name}")
                await interaction_channel.send(content=content, embed=embed)
                return True
                
            if not channel_found:
                logger.error("Could not find announcement channel to send message")
                return False
            
        except Exception as e:
            logger.error(f"Error sending message directly: {e}")
            return False
    except Exception as e:
        logger.error(f"Daily post error: {e}")
        return False

async def handle_daily_command(interaction: Interaction):
    await interaction.response.defer()
    try:
        count = 0
        for user_id in GROUPED_CALENDARS:
            if await post_daily_events(interaction.client, user_id, date.today(), interaction.channel):
                count += 1
        await interaction.followup.send(f"Posted daily events for {count} users")
    except Exception as e:
        logger.error(f"Daily command error: {e}")
        await interaction.followup.send("⚠️ Failed to post daily events")

async def register(bot: discord.Client):
    @bot.tree.command(name="daily")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def daily_command(interaction: discord.Interaction):
        """Post daily summaries to announcement channel"""
        await handle_daily_command(interaction)
