# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                      BOT BACKGROUND TASKS ENTRYPOINT                       ║
# ║   Re-exports functions and state from specialized task modules             ║
# ╚════════════════════════════════════════════════════════════════════════════╝
"""
tasks.py: Entry point for scheduled tasks and background processes.

This module has been refactored to delegate functionality to specialized modules
in the tasks/ subfolder. This improves maintainability and organization.
It primarily serves to re-export necessary functions and shared state variables
for backward compatibility and easier access.
"""
# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SHARED STATE IMPORTS                                                      ║
# ╚════════════════════════════════════════════════════════════════════════════╝
# Import and re-export shared state first to avoid circular imports
from bot.tasks import (
    _task_last_success,
    _task_locks,
    _task_error_counts,
    _MAX_CONSECUTIVE_ERRORS,
    _HEALTH_CHECK_INTERVAL
)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CORE TASK FUNCTIONALITY RE-EXPORTS                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝
# Re-export main functionality for backward compatibility
from bot.tasks import setup_tasks, start_all_tasks

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SPECIALIZED TASK MODULE RE-EXPORTS                                        ║
# ╚════════════════════════════════════════════════════════════════════════════╝
# Re-export functionality from specialized modules

# --- Health Monitoring (from bot.tasks.health) ---
from bot.tasks.health import (
    TaskLock,
    update_task_health,
    monitor_task_health,
    check_tasks_running,
    try_start_task
)

# --- Daily Posting (from bot.tasks.daily_posts) ---
from bot.tasks.daily_posts import (
    schedule_daily_posts,
    post_todays_happenings,
    post_all_daily_events_to_channel
)

# --- Weekly Posting (from bot.tasks.weekly_posts) ---
from bot.tasks.weekly_posts import (
    post_weekly_schedule,
    is_in_current_week
)

# --- Event Monitoring (from bot.tasks.event_monitor) ---
from bot.tasks.event_monitor import (
    watch_for_event_changes,
    initialize_event_snapshots,
    check_for_missed_events
)

# --- Utilities (from bot.tasks.utilities) ---
from bot.tasks.utilities import send_embed

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EXPORT LIST (__all__)                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝
# Define what symbols should be exported when using "from bot.tasks import *"
__all__ = [
    # Core setup
    'setup_tasks',
    'start_all_tasks',
    # Health monitoring
    'TaskLock',
    'update_task_health',
    'monitor_task_health',
    'check_tasks_running',
    'try_start_task',
    # Daily posts
    'schedule_daily_posts',
    'post_todays_happenings',
    'post_all_daily_events_to_channel',
    # Weekly posts
    'post_weekly_schedule',
    'is_in_current_week',
    # Event monitoring
    'watch_for_event_changes',
    'initialize_event_snapshots',
    'check_for_missed_events',
    # Utilities
    'send_embed'
]
