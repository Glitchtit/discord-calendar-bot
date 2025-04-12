"""
Task health monitoring and management.

Handles:
- Monitoring task health
- Restarting failed tasks
- Preventing deadlocks
"""
import asyncio
from datetime import datetime
from discord.ext import tasks

from utils.logging import logger

# Import shared variables from the package
from bot.tasks import (
    _task_locks, 
    _task_last_success, 
    _task_error_counts, 
    _MAX_CONSECUTIVE_ERRORS,
    _HEALTH_CHECK_INTERVAL
)

class TaskLock:
    """Context manager for safely acquiring and releasing task locks"""
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.acquired = False
        
    async def __aenter__(self):
        if self.task_name in _task_locks and _task_locks[self.task_name]:
            logger.debug(f"Task {self.task_name} already running, skipping this iteration")
            return False
            
        _task_locks[self.task_name] = True
        self.acquired = True
        return True
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            _task_locks[self.task_name] = False
        
        if exc_type:
            # Log the exception but don't re-raise, allowing tasks to continue
            _task_error_counts[self.task_name] = _task_error_counts.get(self.task_name, 0) + 1
            logger.exception(f"Error in task {self.task_name}: {exc_val}")
            return True  # Suppress the exception

def update_task_health(task_name: str, success: bool = True) -> None:
    """Updates task health metrics and restarts failed tasks if needed"""
    if success:
        _task_last_success[task_name] = datetime.now()
        _task_error_counts[task_name] = 0
    else:
        error_count = _task_error_counts.get(task_name, 0) + 1
        _task_error_counts[task_name] = error_count
        
        # Log increasing error counts
        if error_count >= 3:
            logger.warning(f"Task {task_name} has failed {error_count} consecutive times")

def get_task_name(task_func):
    """Safely get the name of a task function or Loop object."""
    if hasattr(task_func, "__name__"):
        return task_func.__name__
    elif hasattr(task_func, "get_name"):
        return task_func.get_name()
    elif hasattr(task_func, "_name"):
        return task_func._name
    else:
        # Try to get the string representation and extract useful information
        task_str = str(task_func)
        if "bound method" in task_str:
            # Extract method name from representation like "<bound method post_weekly_schedule of <...>>"
            parts = task_str.split(" ")
            if len(parts) > 2:
                return parts[2]
        # Last resort: return the task's class name
        return task_func.__class__.__name__

async def try_start_task(task_func, bot):
    """Try to start a task, handling various task types appropriately."""
    try:
        # Get task name safely
        task_name = get_task_name(task_func)
        
        # Check if it's a discord.ext.tasks.Loop object
        if hasattr(task_func, "start"):
            if not task_func.is_running():
                task_func.start(bot)
                logger.info(f"Started task: {task_name}")
        # Regular coroutine function
        else:
            asyncio.create_task(task_func(bot))
            logger.info(f"Started task: {task_name}")
    except Exception as e:
        # Get task name safely, even in exception handler
        task_name = get_task_name(task_func)
        logger.exception(f"Failed to start task {task_name}: {e}")

async def check_tasks_running():
    """
    Verifies that all scheduled tasks are still running.
    Returns True if all tasks are running, False if any need to be restarted.
    """
    try:
        # Check if task objects exist and are not done/cancelled
        tasks_running = True
        
        # Check daily task
        if not hasattr(check_tasks_running, "daily_task") or \
           check_tasks_running.daily_task.done() or \
           check_tasks_running.daily_task.cancelled():
            tasks_running = False
            
        # Check weekly task  
        if not hasattr(check_tasks_running, "weekly_task") or \
           check_tasks_running.weekly_task.done() or \
           check_tasks_running.weekly_task.cancelled():
            tasks_running = False
            
        # Check snapshot task
        if not hasattr(check_tasks_running, "snapshot_task") or \
           check_tasks_running.snapshot_task.done() or \
           check_tasks_running.snapshot_task.cancelled():
            tasks_running = False
        
        return tasks_running
    except Exception as e:
        logger.exception(f"Error checking task status: {e}")
        return False

@tasks.loop(minutes=10)
async def monitor_task_health(bot):
    """Monitors and restarts tasks that have failed or become inactive"""
    task_name = "monitor_task_health"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            now = datetime.now()
            
            # Import here to avoid circular imports
            from .daily_posts import schedule_daily_posts
            from .weekly_posts import post_weekly_schedule
            from .event_monitor import watch_for_event_changes
            from .event_monitor import check_for_missed_events
            
            # Check all registered tasks
            all_tasks = {
                "schedule_daily_posts": schedule_daily_posts,
                "watch_for_event_changes": watch_for_event_changes,
                "monitor_task_health": monitor_task_health,
                "post_weekly_schedule": post_weekly_schedule
            }
            
            tasks_recovered = False
            
            for task_name, task_func in all_tasks.items():
                # Check error count
                error_count = _task_error_counts.get(task_name, 0)
                if error_count >= _MAX_CONSECUTIVE_ERRORS:
                    logger.warning(f"Task {task_name} has {error_count} consecutive errors. Restarting...")
                    if task_func.is_running():
                        task_func.cancel()
                    _task_error_counts[task_name] = 0
                    _task_locks[task_name] = False  # Release lock if stuck
                    
                    # Wait a moment before restarting
                    await asyncio.sleep(2)
                    try_start_task(task_func, bot)
                    tasks_recovered = True
                    continue
                    
                # Check for deadlocks (task locked for too long)
                if _task_locks.get(task_name, False):
                    last_success = _task_last_success.get(task_name)
                    if last_success and (now - last_success) > _HEALTH_CHECK_INTERVAL:
                        logger.warning(f"Task {task_name} appears deadlocked. Forcing lock release.")
                        _task_locks[task_name] = False
                        tasks_recovered = True
                
                # Ensure task is running
                if not task_func.is_running():
                    logger.warning(f"Task {task_name} is not running. Restarting...")
                    try_start_task(task_func, bot)
                    tasks_recovered = True
            
            # Verify overall task health using the check_tasks_running function
            if not await check_tasks_running():
                logger.warning("Task health check indicates issues with background tasks")
                # Try to heal the system
                for task_name, task_func in all_tasks.items():
                    if not task_func.is_running():
                        logger.info(f"Attempting recovery of task: {task_name}")
                        try_start_task(task_func, bot)
                        tasks_recovered = True
            
            # If we recovered tasks, check for missed events
            if tasks_recovered:
                logger.info("Tasks were recovered, checking for missed events...")
                try:
                    await check_for_missed_events(bot)
                except Exception as missed_events_error:
                    logger.error(f"Error checking for missed events: {missed_events_error}")
                    
            # Self-update health status
            update_task_health(task_name, True)
            
            # Log periodic health status (every hour)
            if now.minute < 10:  # Only log once an hour
                running_tasks = [name for name, func in all_tasks.items() if func.is_running()]
                logger.info(f"Task health monitor: {len(running_tasks)}/{len(all_tasks)} tasks running")
                for name, func in all_tasks.items():
                    status = "RUNNING" if func.is_running() else "STOPPED"
                    errors = _task_error_counts.get(name, 0)
                    logger.info(f"  - {name}: {status} (errors: {errors})")
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            # Don't update own health to avoid self-restarting logic
