from datetime import date
import discord
import asyncio
from discord import Interaction
from bot.events import GROUPED_CALENDARS, get_events
from .utilities import send_embed
from utils.logging import logger
from utils import format_message_lines
from utils.markdown_formatter import format_daily_message

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
            
        # Fix: Create a dictionary with calendar name as the key and events as the value
        events_by_calendar = {}
        for meta in sources:
            calendar_name = meta.get('name', 'Calendar')
            calendar_events = [e for e in events if e.get('calendar_id') == meta.get('calendar_id')]
            if calendar_events:
                events_by_calendar[calendar_name] = calendar_events
        
        # Format the message with Markdown
        message = format_daily_message(user_id, events_by_calendar, day, is_public=True)
        
        # Check if this is a server-wide calendar (user_id = "1")
        is_server_wide = user_id == "1"
        
        # Create a fallback content string that will ensure the message isn't empty
        content = ""
        if is_server_wide:
            content = "@everyone"
            
        try:
            # Find announcement channel from server configs
            from config.server_config import get_all_server_ids, load_server_config
            
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
                        await channel.send(content=content, content_type="text/markdown", content=message)
                        logger.info(f"Sent calendar update to channel {channel.name}")
                        channel_found = True
                        return True
                else:
                    logger.debug(f"Server {server_id} has no announcement_channel_id configured")
            
            # If no channel found from configs, try the interaction channel as fallback
            if not channel_found and interaction_channel:
                logger.info(f"Using interaction channel as fallback: {interaction_channel.name}")
                await interaction_channel.send(content=content, content_type="text/markdown", content=message)
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
        await interaction.followup.send(f"📝 Posted daily events for {count} users")
    except Exception as e:
        logger.error(f"Daily command error: {e}")
        await interaction.followup.send("⚠️ Failed to post daily events")

async def register(bot: discord.Client):
    @bot.tree.command(name="daily")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def daily_command(interaction: discord.Interaction):
        """Post daily summaries to announcement channel"""
        await handle_daily_command(interaction)
