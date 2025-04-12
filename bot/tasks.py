"""
tasks.py: Entry point for scheduled tasks and background processes.

This module has been refactored to delegate functionality to specialized modules
in the tasks/ subfolder. This improves maintainability and organization.
"""
# Import and re-export shared state first to avoid circular imports
from bot.tasks import (
    _task_last_success,
    _task_locks,
    _task_error_counts,
    _MAX_CONSECUTIVE_ERRORS,
    _HEALTH_CHECK_INTERVAL
)

# Re-export main functionality for backward compatibility
from bot.tasks import setup_tasks, start_all_tasks

# Re-export functionality from specialized modules
from bot.tasks.health import (
    TaskLock,
    update_task_health,
    monitor_task_health,
    check_tasks_running,
    try_start_task
)

from bot.tasks.daily_posts import (
    schedule_daily_posts,
    post_todays_happenings,
    post_all_daily_events_to_channel
)

from bot.tasks.weekly_posts import (
    post_weekly_schedule,
    is_in_current_week
)

from bot.tasks.event_monitor import (
    watch_for_event_changes,
    initialize_event_snapshots,
    check_for_missed_events
)

from bot.tasks.utilities import send_embed

# Define what symbols should be exported when using "from bot.tasks import *"
__all__ = [
    'setup_tasks',
    'start_all_tasks',
    'TaskLock',
    'update_task_health',
    'monitor_task_health',
    'check_tasks_running',
    'try_start_task',
    'schedule_daily_posts',
    'post_todays_happenings',
    'post_all_daily_events_to_channel',
    'post_weekly_schedule',
    'is_in_current_week',
    'watch_for_event_changes',
    'initialize_event_snapshots',
    'check_for_missed_events',
    'send_embed'
]
