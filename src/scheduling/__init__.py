import asyncio
from datetime import datetime, timedelta, time
from typing import Optional
from src.core.logger import logger
from src.core.environment import DEBUG

# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⏰ Task Scheduler                                                   ║
# ║ Handles periodic tasks like daily announcements                    ║
# ╚════════════════════════════════════════════════════════════════════╝

class TaskScheduler:
    """Manages scheduled tasks for the bot."""
    
    def __init__(self):
        self.running_tasks = {}
        self.stop_events = {}
    
    def schedule_daily_task(self, task_name: str, coro_func, hour: int = 8, minute: int = 0):
        """Schedule a coroutine to run daily at a specific time."""
        if task_name in self.running_tasks:
            logger.warning(f"Task {task_name} is already scheduled")
            return
        
        stop_event = asyncio.Event()
        self.stop_events[task_name] = stop_event
        
        task = asyncio.create_task(
            self._daily_task_loop(task_name, coro_func, hour, minute, stop_event)
        )
        self.running_tasks[task_name] = task
        logger.info(f"Scheduled daily task '{task_name}' for {hour:02d}:{minute:02d}")
    
    async def _daily_task_loop(self, task_name: str, coro_func, hour: int, minute: int, stop_event: asyncio.Event):
        """Internal loop for daily tasks."""
        while not stop_event.is_set():
            try:
                # Calculate next run time
                now = datetime.now()
                target_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # If target time has passed today, schedule for tomorrow
                if target_time <= now:
                    target_time += timedelta(days=1)
                
                sleep_duration = (target_time - now).total_seconds()
                
                # In debug mode, run more frequently for testing
                if DEBUG and sleep_duration > 300:  # If more than 5 minutes away
                    logger.debug(f"Debug mode: Running {task_name} immediately instead of waiting {sleep_duration:.0f} seconds")
                    sleep_duration = 5  # Run in 5 seconds
                
                logger.info(f"Task '{task_name}' scheduled to run at {target_time} (in {sleep_duration:.0f} seconds)")
                
                # Wait until target time or stop signal
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=sleep_duration)
                    break  # Stop event was set
                except asyncio.TimeoutError:
                    pass  # Time to run the task
                
                # Run the task
                logger.info(f"Executing task: {task_name}")
                try:
                    await coro_func()
                    logger.info(f"Task '{task_name}' completed successfully")
                except Exception as e:
                    logger.exception(f"Error in task '{task_name}': {e}")
                
            except Exception as e:
                logger.exception(f"Error in task loop for '{task_name}': {e}")
                # Wait a bit before retrying to avoid rapid error loops
                await asyncio.sleep(60)
    
    def stop_task(self, task_name: str):
        """Stop a scheduled task."""
        if task_name in self.stop_events:
            self.stop_events[task_name].set()
            logger.info(f"Stopping task: {task_name}")
        
        if task_name in self.running_tasks:
            task = self.running_tasks[task_name]
            if not task.done():
                task.cancel()
            del self.running_tasks[task_name]
            del self.stop_events[task_name]
    
    def stop_all_tasks(self):
        """Stop all scheduled tasks."""
        logger.info("Stopping all scheduled tasks...")
        for task_name in list(self.running_tasks.keys()):
            self.stop_task(task_name)
        logger.info("All tasks stopped")
    
    def get_task_status(self) -> dict:
        """Get status of all scheduled tasks."""
        status = {}
        for task_name, task in self.running_tasks.items():
            status[task_name] = {
                "running": not task.done(),
                "cancelled": task.cancelled() if task.done() else False,
                "exception": str(task.exception()) if task.done() and task.exception() else None
            }
        return status

# Global scheduler instance
scheduler = TaskScheduler()

def get_scheduler() -> TaskScheduler:
    """Get the global task scheduler instance."""
    return scheduler