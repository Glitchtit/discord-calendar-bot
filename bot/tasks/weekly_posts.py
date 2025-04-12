"""
Weekly event posting tasks and utilities.

Handles scheduling and posting of weekly calendar summaries.
"""
from datetime import datetime, date, timedelta
from discord.ext import tasks

from utils.logging import logger
from utils import get_monday_of_week
from bot.events import GROUPED_CALENDARS
from .health import TaskLock, update_task_health
from . import _task_last_success, _task_error_counts

def is_in_current_week(event, today):
    """Check if an event is within the current week."""
    try:
        start_container = event.get("start", {})
        if "date" in start_container:
            event_date = datetime.fromisoformat(start_container["date"]).date()
        elif "dateTime" in start_container:
            event_date = datetime.fromisoformat(start_container["dateTime"]).date()
        else:
            return False
            
        # Check if event is within this week
        monday = get_monday_of_week(today)
        sunday = monday + timedelta(days=6)
        return monday <= event_date <= sunday
    except Exception as e:
        logger.warning(f"Error checking if event is in current week: {e}")
        return False

@tasks.loop(minutes=30)  # Check every 30 minutes
async def post_weekly_schedule(bot):
    """Post weekly schedule every Monday at 07:00"""
    try:
        async with TaskLock('weekly_schedule') as acquired:
            if not acquired:
                return
                
            now = datetime.now()
            today = date.today()
            
            # Only run on Mondays between 7:00 and 7:30 AM
            if today.weekday() == 0 and 7 <= now.hour < 8:
                logger.info("🔄 Running scheduled weekly posting (Monday morning)")
                
                # Get the Monday of the current week (which is today since it's Monday)
                this_monday = today
                
                count = 0
                for user_id in GROUPED_CALENDARS:
                    from bot.commands.weekly import post_weekly_events
                    if await post_weekly_events(bot, user_id, this_monday, None):
                        count += 1
                
                logger.info(f"📝 Auto-posted weekly events for {count} users")
                
                # Record successful task execution
                _task_last_success['weekly_schedule'] = datetime.now()
                _task_error_counts['weekly_schedule'] = 0
                
    except Exception as e:
        logger.error(f"Weekly schedule auto-post error: {e}")
        # Increment error count for health monitoring
        _task_error_counts['weekly_schedule'] = _task_error_counts.get('weekly_schedule', 0) + 1
