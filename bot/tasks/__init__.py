# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                       BOT TASKS PACKAGE INIT                         ║
# ║    Initializes the tasks package, defines shared health monitoring       ║
# ║    variables, imports task modules, and provides setup functions.        ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
tasks package: Contains scheduled task modules for the Discord bot.
"""
from datetime import timedelta

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SHARED TASK HEALTH MONITORING GLOBALS                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

_task_last_success = {} # Tracks last successful run time for each task
_task_locks = {}        # Locks to prevent concurrent runs of the same task
_task_error_counts = {} # Tracks consecutive errors for each task
_MAX_CONSECUTIVE_ERRORS = 5 # Threshold for considering a task unhealthy
_HEALTH_CHECK_INTERVAL = timedelta(hours=1) # How often to run the health monitor

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TASK MODULE IMPORTS                                                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

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

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ TASK SETUP FUNCTIONS                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- setup_tasks ---
# Configures and starts all scheduled tasks for the bot.
# Initializes the health tracking dictionaries.
# Starts the main background tasks (daily posts, event monitor, health monitor, weekly posts).
# Includes error handling to attempt starting tasks individually if the group start fails.
# Args:
#     bot: The discord.py Bot instance.
# Returns: True if all tasks started successfully initially, False otherwise.
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

# --- start_all_tasks ---
# Synchronous wrapper around setup_tasks.
# Used for recovery scenarios where tasks might need restarting without async context.
# Args:
#     bot: The discord.py Bot instance.
# Returns: The result of setup_tasks (True or False).
def start_all_tasks(bot):
    """Start all tasks (used for recovery scenarios)"""
    return setup_tasks(bot)