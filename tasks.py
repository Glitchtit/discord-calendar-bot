"""
tasks.py: Scheduled tasks for calendar monitoring and notifications.

Contains tasks that:
1. Post daily and weekly calendar summaries
2. Monitor for changes in calendar events
3. Generate AI-powered morning greetings
4. Self-monitor task health

Note: All tasks now work with server-specific configurations loaded via
the /setup command, rather than the deprecated environment variables.
"""

from datetime import datetime, timedelta
from dateutil import tz
from discord.ext import tasks
import asyncio
import random
import time
from typing import Dict, Optional, Set

from utils import (
    get_today,
    get_monday_of_week,
    is_in_current_week,
    format_event,
    get_local_timezone
)
from commands import (
    post_tagged_week,
    post_tagged_events,
    send_embed
)
from events import (
    GROUPED_CALENDARS,  # Now populated from server-specific configs
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    load_previous_events,
    save_current_events_for_key,
    compute_event_fingerprint
)
from log import logger
from ai import generate_greeting, generate_image

# Task health monitoring
_task_last_success = {}
_task_locks = {}
_task_error_counts = {}
_MAX_CONSECUTIVE_ERRORS = 5
_HEALTH_CHECK_INTERVAL = timedelta(hours=1)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔒 TaskLock                                                        ║
# ║ Context manager for safely acquiring and releasing task locks     ║
# ╚════════════════════════════════════════════════════════════════════╝
class TaskLock:
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.acquired = False
        
    async def __aenter__(self):
        global _task_locks
        if self.task_name in _task_locks and _task_locks[self.task_name]:
            logger.debug(f"Task {self.task_name} already running, skipping this iteration")
            return False
            
        _task_locks[self.task_name] = True
        self.acquired = True
        return True
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        global _task_locks
        if self.acquired:
            _task_locks[self.task_name] = False
        
        if exc_type:
            # Log the exception but don't re-raise, allowing tasks to continue
            global _task_error_counts
            _task_error_counts[self.task_name] = _task_error_counts.get(self.task_name, 0) + 1
            logger.exception(f"Error in task {self.task_name}: {exc_val}")
            return True  # Suppress the exception

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🩺 update_task_health                                              ║
# ║ Updates task health metrics and restarts failed tasks if needed    ║
# ╚════════════════════════════════════════════════════════════════════╝
def update_task_health(task_name: str, success: bool = True) -> None:
    global _task_last_success, _task_error_counts
    
    if success:
        _task_last_success[task_name] = datetime.now()
        _task_error_counts[task_name] = 0
    else:
        error_count = _task_error_counts.get(task_name, 0) + 1
        _task_error_counts[task_name] = error_count
        
        # Log increasing error counts
        if error_count >= 3:
            logger.warning(f"Task {task_name} has failed {error_count} consecutive times")

# ╔════════════════════════════════════════════════════════════════════╗
# 🧰 Utility: safe_call
# ╚════════════════════════════════════════════════════════════════════╝
def start_all_tasks(bot):
    try:
        # Initialize task health tracking
        global _task_last_success, _task_locks, _task_error_counts
        _task_last_success = {}
        _task_locks = {}
        _task_error_counts = {}
        
        # Start primary tasks
        schedule_daily_posts.start(bot)
        watch_for_event_changes.start(bot)
        
        # Start health monitoring
        monitor_task_health.start(bot)
        
        logger.info("All scheduled tasks started successfully")
    except Exception as e:
        logger.exception(f"Error starting tasks: {e}")
        
        # Try to start tasks individually
        try_start_task(schedule_daily_posts, bot)
        try_start_task(watch_for_event_changes, bot)
        try_start_task(monitor_task_health, bot)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 try_start_task                                                  ║
# ║ Attempts to start a specific task, handling any exceptions         ║
# ╚════════════════════════════════════════════════════════════════════╝
def try_start_task(task_func, *args, **kwargs):
    try:
        if not task_func.is_running():
            task_func.start(*args, **kwargs)
            logger.info(f"Started task: {task_func.__name__}")
        else:
            logger.info(f"Task already running: {task_func.__name__}")
    except Exception as e:
        logger.exception(f"Failed to start task {task_func.__name__}: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 AI Greeting
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=1)
async def schedule_daily_posts(bot):
    task_name = "schedule_daily_posts"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            # Use utils' timezone-safe function
            local_now = datetime.now(tz=get_local_timezone())
            today = local_now.date()

            # Monday 08:00 — Post weekly summaries
            if local_now.weekday() == 0 and local_now.hour == 8 and local_now.minute == 0:
                logger.info("Starting weekly summary posting")
                monday = get_monday_of_week(today)
                
                for tag in list(GROUPED_CALENDARS.keys()):  # Use list() to prevent dict changed during iteration
                    try:
                        await post_tagged_week(bot, tag, monday)
                        # Small delay between posts to avoid rate limits
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.exception(f"Error posting weekly summary for tag {tag}: {e}")

            # Daily 08:01 — Post today's agenda and greeting
            if local_now.hour == 8 and local_now.minute == 1:
                logger.info("Starting daily posts with greeting")
                await post_todays_happenings(bot, include_greeting=True)
                
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            
            # Add a small delay before the next iteration if we hit an error
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════╗
# 📅 Daily Event Poster — Posts today's events for each tag
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=5)  # Reduced frequency for stability
async def watch_for_event_changes(bot):
    task_name = "watch_for_event_changes"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            today = get_today()
            monday = get_monday_of_week(today)
            processed_tags = set()

            # Process calendars in batches to avoid overloading
            for tag, calendars in GROUPED_CALENDARS.items():
                # Skip if we've already processed too many in this cycle
                if len(processed_tags) >= 3:  # Process max 3 tags per cycle
                    break
                    
                # Add small delay between calendar checks to avoid rate limiting
                if processed_tags:
                    await asyncio.sleep(2)
                
                earliest = today - timedelta(days=30)
                latest = today + timedelta(days=90)
                processed_tags.add(tag)

                # Fetch and fingerprint all events in the date window
                all_events = []
                for meta in calendars:
                    try:
                        # Rate limit ourselves to avoid overloading APIs
                        events = await asyncio.to_thread(get_events, meta, earliest, latest)
                        if not events:
                            events = []
                        all_events += events
                    except Exception as e:
                        logger.exception(f"Error fetching events for calendar {meta['name']}: {e}")
                        
                # Skip further processing if we couldn't fetch any events
                if not all_events:
                    continue
                        
                # Sort events reliably to ensure consistent fingerprinting
                all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))

                # Compare with previous snapshot
                key = f"{tag}_full"
                prev_snapshot = load_previous_events().get(key, [])
                
                # Create fingerprints, with added error handling
                prev_fps = {}
                curr_fps = {}
                
                for e in prev_snapshot:
                    try:
                        fp = compute_event_fingerprint(e)
                        if fp:  # Only add valid fingerprints
                            prev_fps[fp] = e
                    except Exception as ex:
                        logger.warning(f"Error fingerprinting previous event: {ex}")
                
                for e in all_events:
                    try:
                        fp = compute_event_fingerprint(e)
                        if fp:  # Only add valid fingerprints 
                            curr_fps[fp] = e
                    except Exception as ex:
                        logger.warning(f"Error fingerprinting current event: {ex}")

                # Find added and removed events
                added = [e for fp, e in curr_fps.items() if fp not in prev_fps]
                removed = [e for fp, e in prev_fps.items() if fp not in curr_fps]

                # Limit notifications to events in this week
                added_week = [e for e in added if is_in_current_week(e, today)]
                removed_week = [e for e in removed if is_in_current_week(e, today)]

                if added_week or removed_week:
                    try:
                        lines = []
                        if added_week:
                            lines.append("**📥 Added Events This Week:**")
                            lines += [f"➕ {format_event(e)}" for e in added_week]
                        if removed_week:
                            lines.append("**📤 Removed Events This Week:**")
                            lines += [f"➖ {format_event(e)}" for e in removed_week]

                        await send_embed(
                            bot,
                            title=f"📣 Event Changes – {get_name_for_tag(tag)}",
                            description="\n".join(lines),
                            color=get_color_for_tag(tag)
                        )
                        logger.info(f"Detected changes for '{tag}', snapshot updated.")
                        save_current_events_for_key(meta["server_id"], f"{tag}_full", all_events)
                    except Exception as e:
                        logger.exception(f"Error posting changes for tag {tag}: {e}")
                else:
                    # Only save if we have data and it differs from previous
                    if all_events and (len(all_events) != len(prev_snapshot)):
                        save_current_events_for_key(meta["server_id"], f"{tag}_full", all_events)
                        logger.debug(f"Updated snapshot for '{tag}' with {len(all_events)} events")
                    else:
                        logger.debug(f"No changes for '{tag}'. Snapshot unchanged.")
                    
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            
            # Add a small delay before the next iteration if we hit an error
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🩺 monitor_task_health                                             ║
# ║ Monitors and restarts tasks that have failed or become inactive   ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=10)
async def monitor_task_health(bot):
    task_name = "monitor_task_health"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            global _task_last_success, _task_error_counts, _task_locks
            now = datetime.now()
            
            # Check all registered tasks
            all_tasks = {
                "schedule_daily_posts": schedule_daily_posts,
                "watch_for_event_changes": watch_for_event_changes
            }
            
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
                    continue
                    
                # Check for deadlocks (task locked for too long)
                if _task_locks.get(task_name, False):
                    last_success = _task_last_success.get(task_name)
                    if last_success and (now - last_success) > _HEALTH_CHECK_INTERVAL:
                        logger.warning(f"Task {task_name} appears deadlocked. Forcing lock release.")
                        _task_locks[task_name] = False
                
                # Ensure task is running
                if not task_func.is_running():
                    logger.warning(f"Task {task_name} is not running. Restarting...")
                    try_start_task(task_func, bot)
                    
            # Self-update health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            # Don't update own health to avoid self-restarting logic

# ╔════════════════════════════════════════════════════════════════════╗
# 📜 Weekly Summary Poster — Runs Mondays at 06:10
# ╚════════════════════════════════════════════════════════════════════╝
async def post_todays_happenings(bot, include_greeting: bool = False):
    try:
        today = get_today()
        all_events_for_greeting = []
        tag_count = 0
        success_count = 0
        error_count = 0

        # Post events for each tag
        for tag in GROUPED_CALENDARS:
            tag_count += 1
            try:
                # Post events for this tag
                posted = await post_tagged_events(bot, tag, today)
                if posted:
                    success_count += 1
                    
                # Add small delay between posts to avoid rate limiting
                if tag_count > 1:
                    await asyncio.sleep(1)
                    
                # Get events for greeting generation
                for meta in GROUPED_CALENDARS[tag]:
                    try:
                        events = await asyncio.to_thread(get_events, meta, today, today)
                        if not events:
                            events = []
                        all_events_for_greeting += events
                    except Exception as e:
                        logger.warning(f"Error fetching greeting events for {meta['name']}: {e}")
            except Exception as e:
                error_count += 1
                logger.exception(f"Error posting events for tag {tag}: {e}")

        # Generate and post greeting if requested
        if include_greeting and (success_count > 0 or tag_count == 0):
            retry_count = 0
            max_retries = 2
            
            while retry_count <= max_retries:
                try:
                    # Get user names if possible
                    guild = None
                    for g in bot.guilds:
                        if g.member_count > 0:  # Find a guild with members
                            guild = g
                            break
                            
                    user_names = []
                    if guild:
                        user_names = [
                            m.nick or m.display_name for m in guild.members 
                            if not m.bot and m.name  # Ensure valid name/nickname
                        ]
                    
                    # Get event titles for greeting context
                    event_titles = []
                    for e in all_events_for_greeting:
                        title = e.get("summary")
                        if title and isinstance(title, str):
                            event_titles.append(title)
                    
                    # Generate greeting with appropriate timeouts
                    greeting, persona = await asyncio.wait_for(
                        asyncio.to_thread(generate_greeting, event_titles, user_names),
                        timeout=30
                    )

                    if greeting:
                        # Generate image with timeout
                        image_path = None
                        try:
                            image_path = await asyncio.wait_for(
                                asyncio.to_thread(generate_image, greeting, persona),
                                timeout=60
                            )
                        except asyncio.TimeoutError:
                            logger.warning("Image generation timed out, continuing without image")
                        
                        # Send the greeting embed
                        await send_embed(
                            bot,
                            title=f"The Morning Proclamation 📜 — {persona}",
                            description=greeting,
                            color=0xffe4b5,
                            image_path=image_path
                        )
                    break  # Success, exit retry loop
                    
                except asyncio.TimeoutError:
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning(f"Greeting generation timed out, retrying ({retry_count}/{max_retries})")
                        await asyncio.sleep(2)
                    else:
                        logger.error("Max retries reached for greeting generation")
                except Exception as e:
                    logger.exception(f"Error generating or posting greeting: {e}")
                    break  # Don't retry on general errors
                    
        # Log error summary 
        if error_count > 0:
            logger.warning(f"Completed with {error_count} errors, {success_count} successes")
    except Exception as e:
        logger.exception(f"Error in post_todays_happenings: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Background Scheduler
# ╚════════════════════════════════════════════════════════════════════╝
async def initialize_event_snapshots():
    try:
        logger.info("Performing initial silent snapshot of all calendars...")
        today = get_today()
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)
        
        total_calendars = sum(len(cals) for cals in GROUPED_CALENDARS.values())
        processed = 0
        failed = 0

        # Process tags sequentially to avoid overloading APIs
        for tag, calendars in GROUPED_CALENDARS.items():
            try:
                # Add a delay between tag processing to avoid rate limits
                if processed > 0:
                    await asyncio.sleep(2)
                    
                # Gather events from all calendars for this tag
                all_events = []
                for meta in calendars:
                    try:
                        events = await asyncio.to_thread(get_events, meta, earliest, latest)
                        if not events:
                            events = []
                        all_events += events
                        processed += 1
                        
                        # Small delay between calendar fetches
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        failed += 1
                        logger.exception(f"Error fetching events for calendar {meta['name']}: {e}")
                
                # Only save if we got events
                if all_events:
                    # Sort before saving for consistent fingerprinting
                    all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
                    save_current_events_for_key(meta["server_id"], f"{tag}_full", all_events)
                    logger.debug(f"Initial snapshot saved for '{tag}' with {len(all_events)} events")
                else:
                    logger.warning(f"No events found for tag '{tag}' during initialization")
            except Exception as e:
                failed += 1
                logger.exception(f"Error initializing snapshot for tag {tag}: {e}")

        status = "complete" if failed == 0 else f"partial (failed: {failed})"
        logger.info(f"Initial snapshot {status}. Processed {processed}/{total_calendars} calendars.")
    except Exception as e:
        logger.exception(f"Error in initialize_event_snapshots: {e}")
