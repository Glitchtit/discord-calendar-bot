"""
tasks package: Contains scheduled task modules for the Discord bot.
"""
from datetime import timedelta

# Task health monitoring globals (shared between modules)
_task_last_success = {}
_task_locks = {}
_task_error_counts = {}
_MAX_CONSECUTIVE_ERRORS = 5
_HEALTH_CHECK_INTERVAL = timedelta(hours=1)

# Import the task modules after defining the shared variables
from .health import (
    TaskLock, 
    update_task_health,
    monitor_task_health, 
    check_tasks_running,
    try_start_task
)

from .daily_posts import (
    schedule_daily_posts,
    post_todays_happenings,
    post_all_daily_events_to_channel
)

from .weekly_posts import (
    post_weekly_schedule,
    is_in_current_week
)

from .event_monitor import (
    watch_for_event_changes,
    initialize_event_snapshots,
    check_for_missed_events
)

from .utilities import (
    send_embed
)

def setup_tasks(bot):
    """Configure and start all scheduled tasks."""
    try:
        # Initialize task health tracking
        global _task_last_success, _task_locks, _task_error_counts
        _task_last_success = {}
        _task_locks = {}
        _task_error_counts = {}
        
        # Start primary tasks
        schedule_daily_posts.start(bot)
        watch_for_event_changes.start(bot)
        monitor_task_health.start(bot)
        post_weekly_schedule.start(bot)
        
        # Log successful startup
        from utils.logging import logger
        logger.info("✅ All scheduled tasks started successfully")
        return True
    except Exception as e:
        from utils.logging import logger
        logger.exception(f"❌ Error starting tasks: {e}")
        
        # Try to start tasks individually
        try_start_task(schedule_daily_posts, bot)
        try_start_task(watch_for_event_changes, bot)
        try_start_task(monitor_task_health, bot)
        try_start_task(post_weekly_schedule, bot)
        return False

# Make this function synchronous since it's called without await in core.py
def start_all_tasks(bot):
    """Start all tasks (used for recovery scenarios)"""
    return setup_tasks(bot)