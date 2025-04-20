# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                     BOT TASKS DAILY POSTS MODULE                     ║
# ║    Handles the scheduled task for posting daily event summaries to       ║
# ║    configured announcement channels.                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Daily event posting tasks and utilities.

Handles scheduling and posting of daily calendar events.
"""
import asyncio
from datetime import datetime
from discord.ext import tasks
from zoneinfo import ZoneInfo

from utils.logging import logger
from utils import get_today
from bot.events import GROUPED_CALENDARS
from config.server_config import get_all_server_ids, load_server_config, get_announcement_channel_id
from .health import TaskLock, update_task_health
from .utilities import send_embed

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ DAILY POST SCHEDULER TASK                                                 ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- schedule_daily_posts (task loop) ---
# Runs every minute to check if it's time to post daily summaries for any configured server.
# Checks the current time against each server's configured timezone and post time (default 8:00 AM).
# If it's time, calls `post_todays_happenings` for that server.
# Uses TaskLock for concurrency control and updates task health.
# Notifies admins on critical errors.
# Args:
#     bot: The discord.py Bot instance.
@tasks.loop(minutes=1)
async def schedule_daily_posts(bot):
    """Schedule daily posts at specific times"""
    task_name = "schedule_daily_posts"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            # Get current time in UTC
            utc_now = datetime.now(tz=ZoneInfo("UTC"))
            
            # For each configured server, check if we should post based on 
            # their configured timezone and posting times
            for server_id in get_all_server_ids():
                config = load_server_config(server_id)
                
                # Skip servers without proper configuration
                if not config or not isinstance(config, dict):
                    continue
                    
                # Get server timezone (default to UTC if not specified)
                server_timezone_str = config.get("timezone", "UTC")
                try:
                    server_timezone = ZoneInfo(server_timezone_str)
                except Exception:
                    logger.warning(f"Invalid timezone {server_timezone_str} for server {server_id}. Using UTC.")
                    server_timezone = ZoneInfo("UTC")
                
                # Get server local time
                local_now = utc_now.astimezone(server_timezone)
                
                # Check if it's time for daily posts (default: 8am)
                daily_hour = config.get("daily_post_hour", 8)
                daily_minute = config.get("daily_post_minute", 0)
                
                if local_now.hour == daily_hour and local_now.minute == daily_minute:
                    logger.info(f"Starting daily posts for server {server_id} at {local_now.hour}:{local_now.minute} {server_timezone_str}")
                    await post_todays_happenings(bot, server_id=server_id, include_greeting=True)
            
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            
            # Notify admins of the critical error
            try:
                from utils.notifications import notify_critical_error
                await notify_critical_error("Daily Posts Scheduler", e)
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
            
            # Add a small delay before the next iteration if we hit an error
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EVENT POSTING LOGIC                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- post_todays_happenings ---
# Posts the events for the current day to the appropriate announcement channel(s).
# Can optionally include a greeting message.
# If `server_id` is provided, posts only for that server.
# Otherwise, iterates through all configured servers.
# Calls `bot.commands.daily.post_daily_events` to handle the actual fetching and formatting for each user/calendar group.
# Args:
#     bot: The discord.py Bot instance.
#     server_id: Optional server ID to post for a specific server.
#     include_greeting: Boolean flag to include a greeting message.
# Returns: True if events were successfully posted for at least one group, False otherwise.
async def post_todays_happenings(bot, server_id=None, include_greeting: bool = False):
    """Post today's events to the announcement channel, not as DMs"""
    try:
        today = get_today()
        from bot.events import GROUPED_CALENDARS
        
        # If a greeting is requested, generate and post it
        if include_greeting:
            try:
                from bot.commands.greet import post_greeting
                
                # If server_id is specified, get the channel
                if server_id:
                    # Use the getter function
                    channel_id = get_announcement_channel_id(server_id)
                    if channel_id:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            await post_greeting(bot, channel)
                else:
                    # Try to post greeting to all configured announcement channels
                    # Use the getter function
                    for sid in get_all_server_ids():
                        channel_id = get_announcement_channel_id(sid)
                        if channel_id:
                            channel = bot.get_channel(channel_id)
                            if channel:
                                await post_greeting(bot, channel)
            except Exception as e:
                logger.error(f"Error posting greeting: {e}")
        
        # Post daily events for each calendar group
        success_count = 0
        
        # If server_id is specified, only post for that server's calendars
        if server_id:
            for user_id in GROUPED_CALENDARS:
                # Pass the specific server_id to filter only relevant calendars
                from bot.commands.daily import post_daily_events
                if await post_daily_events(bot, user_id, today, server_id=server_id):
                    success_count += 1
        else:
            # Post for all servers
            for user_id in GROUPED_CALENDARS:
                from bot.commands.daily import post_daily_events
                if await post_daily_events(bot, user_id, today):
                    success_count += 1
        
        logger.info(f"Successfully posted daily events for {success_count} calendar groups")
        return success_count > 0
    except Exception as e:
        logger.exception(f"Error in post_todays_happenings: {e}")
        return False

# --- post_all_daily_events_to_channel ---
# Fetches *all* events for a given date (defaults to today) across *all* configured calendars
# for a specific server and posts them in a single embed to that server's announcement channel.
# This is different from `post_todays_happenings` which posts per user/tag.
# Sorts events by time and formats them.
# Includes an @everyone ping if any of the calendars contributing events are server-wide (user_id=None).
# Args:
#     bot: The discord.py Bot instance.
#     date: The date for which to post events (defaults to today).
async def post_all_daily_events_to_channel(bot, date=None):
    """Post all daily events to the announcement channel."""
    if date is None:
        date = get_today()
        
    try:
        # For each server, post events
        for server_id in get_all_server_ids():
            # Use the getter function
            channel_id = get_announcement_channel_id(server_id)
            
            # Skip servers without announcement channel
            if not channel_id:
                continue
                
            channel = bot.get_channel(channel_id)
            if not channel:
                logger.warning(f"Channel ID {channel_id} not found for server {server_id}")
                continue
                
            # Get events for all users/tags
            all_events = []
            has_server_wide_events = False
            
            for user_id, calendars in GROUPED_CALENDARS.items():
                for cal in calendars:
                    if cal.get("server_id") == server_id:
                        from bot.events import get_events
                        events = await asyncio.to_thread(get_events, cal, date, date)
                        if events:
                            # Check if this calendar is server-wide (user_id is None)
                            if cal.get("user_id") is None:
                                has_server_wide_events = True
                            all_events.extend(events)
            
            # If we have events, post them
            if all_events:
                # Sort by start time
                all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
                
                # Format event list
                from utils import format_event
                event_list = [f"- {format_event(event)}" for event in all_events]
                
                # Set content to @everyone if we have server-wide events
                content = "@everyone" if has_server_wide_events else None
                
                # Create embed
                await send_embed(
                    bot,
                    title=f"📅 Events for {date.strftime('%A, %B %d')}",
                    description="\n".join(event_list) if event_list else "No events today!",
                    color=0x3498db,  # Blue color
                    channel=channel,
                    content=content
                )
                
                logger.info(f"Posted {len(all_events)} events to channel {channel.name} in server {server_id}")
    except Exception as e:
        logger.exception(f"Error posting daily events: {e}")
