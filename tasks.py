from datetime import datetime, timedelta
from dateutil import tz
from discord.ext import tasks
import asyncio
import json
import os
import random
import time
from typing import Dict, Optional, Set

from utils import (
    get_today,
    get_monday_of_week,
    is_in_current_week,
    shorten,
    get_local_timezone,
    parse_date_string,
)
from commands import (
    post_tagged_week,
    post_tagged_events,
    send_embed
)
from events import (
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    load_previous_events,
    save_current_events_for_key,
    write_json_atomic,
    compute_event_fingerprint,
    compute_event_core_fingerprint
)
from views import format_change_lines
from log import logger
from ai import generate_greeting, generate_image
from environ import AI_TOGGLE

# Task health monitoring
_task_last_success = {}
_task_locks = {}
_task_error_counts = {}
_MAX_CONSECUTIVE_ERRORS = 5
_HEALTH_CHECK_INTERVAL = timedelta(hours=1)

# Change verification system
_pending_changes = {}  # tag -> {timestamp, added_events, removed_events, changed_events, verification_count}
_VERIFICATION_DELAY = timedelta(minutes=6)  # Wait 6 minutes before re-checking (avoid exact minute boundary issues)
_MAX_VERIFICATION_ATTEMPTS = 3  # Maximum number of verification attempts

# Rotating cursor so watch_for_event_changes covers every tag over successive
# cycles instead of always re-checking the first few.
_watch_tag_cursor = 0

# Per-day posting progress, so a retry within the 08:00 window only covers the
# tags that haven't gone out yet (memory only: see the window comment below)
_post_state: dict = {"date": None}


async def _fetch_calendar_events_safe(meta: dict, start, end, context: str = "", timeout: int = 300) -> list | None:
    """Fetch events from a single calendar with timeout and comprehensive error handling.

    Returns a list of events, or None if the fetch failed. Never raises except
    for CancelledError and KeyboardInterrupt.
    """
    cal_name = meta.get("name", "Unknown")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(get_events, meta, start, end),
            timeout=timeout,
        )
    except asyncio.CancelledError:
        logger.info(f"Event fetching was cancelled{' during ' + context if context else ''}")
        raise
    except KeyboardInterrupt:
        logger.info(f"Calendar processing interrupted by user{' during ' + context if context else ''}")
        raise
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching events from calendar {cal_name}{' during ' + context if context else ''}")
    except MemoryError:
        logger.error(f"Memory error fetching events from calendar {cal_name} - calendar may be too large")
    except (TypeError, AttributeError, KeyError) as e:
        logger.error(f"Data type error fetching events from calendar {cal_name}: {e}")
    except Exception as e:
        logger.exception(f"Error fetching events from calendar {cal_name}{' during ' + context if context else ''}: {e}")
    return None


def _tag_sources(calendars: list) -> list:
    return sorted(m.get("id", "") for m in calendars)


def _needs_baseline(snapshots: dict, tag: str, calendars: list) -> bool:
    """No snapshot yet, or the tag's calendars changed since it was taken: comparing
    would announce a whole added/removed calendar as individual event changes."""
    return f"{tag}_full" not in snapshots or snapshots.get(f"{tag}_sources") != _tag_sources(calendars)


def _save_baseline(tag: str, calendars: list, events: list) -> None:
    save_current_events_for_key(f"{tag}_full", events)
    save_current_events_for_key(f"{tag}_sources", _tag_sources(calendars))


def _event_start_key(e: dict) -> str:
    return e["start"].get("dateTime", e["start"].get("date", ""))


async def _fetch_tag_events(calendars: list, start, end, context: str = "") -> list | None:
    """All events for a tag, sorted. None if ANY calendar failed: a partial result
    would make the failed calendar's events look removed."""
    all_events = []
    for meta in calendars:
        events = await _fetch_calendar_events_safe(meta, start, end, context=context)
        if events is None:
            logger.info(f"Calendar {meta.get('name', 'Unknown')} failed during {context}; skipping tag this cycle")
            return None
        all_events += events
    all_events.sort(key=_event_start_key)
    return all_events

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
            
            # Special handling for certain exception types
            if exc_type == KeyboardInterrupt:
                logger.info(f"Task {self.task_name} interrupted by user")
                return False  # Allow KeyboardInterrupt to propagate for clean shutdown
            elif exc_type == asyncio.CancelledError:
                logger.info(f"Task {self.task_name} was cancelled")
                return False  # Allow cancellation to propagate
            elif exc_type == MemoryError:
                logger.error(f"Memory error in task {self.task_name}: {exc_val}")
                logger.error("This may indicate the calendar data is too large or there's a memory leak")
            elif exc_type in (ConnectionError, TimeoutError):
                logger.warning(f"Network error in task {self.task_name}: {exc_val}")
            else:
                logger.exception(f"Error in task {self.task_name}: {exc_val}")
            
            return True  # Suppress the exception for most cases

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
# ║ 🚀 start_all_tasks                                                 ║
# ║ Activates recurring task loops for scheduling and change watching ║
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
        
        # Start verification watchdog (runs more frequently to catch stuck verifications)
        verification_watchdog.start(bot)
        
        # Start health monitoring tasks
        monitor_task_health.start(bot)
        calendar_health_monitor.start(bot)

        # Start reminder system
        check_reminders.start(bot)
        
        logger.info("All scheduled tasks started successfully")
    except Exception as e:
        logger.exception(f"Error starting tasks: {e}")
        
        # Try to start tasks individually
        try_start_task(schedule_daily_posts, bot)
        try_start_task(watch_for_event_changes, bot)
        try_start_task(verification_watchdog, bot)
        try_start_task(monitor_task_health, bot)
        try_start_task(calendar_health_monitor, bot)
        try_start_task(check_reminders, bot)

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
# ║ 🔍 detect_event_changes                                            ║
# ║ Analyzes events to distinguish between added, removed, and changed ║
# ╚════════════════════════════════════════════════════════════════════╝
def detect_event_changes(prev_events: list, curr_events: list, today) -> tuple:
    """
    Analyze events to detect additions, removals, and changes.
    Returns (added_events, removed_events, changed_events) for events in current week.
    """
    try:
        # Create fingerprint mappings
        prev_fps = {}
        prev_core_fps = {}
        curr_fps = {}
        curr_core_fps = {}
        
        # Build previous event mappings
        for e in prev_events:
            try:
                fp = compute_event_fingerprint(e)
                core_fp = compute_event_core_fingerprint(e)
                if fp and core_fp:
                    prev_fps[fp] = e
                    prev_core_fps[core_fp] = e
            except Exception as ex:
                logger.warning(f"Error fingerprinting previous event: {ex}")
                continue
        
        # Build current event mappings
        for e in curr_events:
            try:
                fp = compute_event_fingerprint(e)
                core_fp = compute_event_core_fingerprint(e)
                if fp and core_fp:
                    curr_fps[fp] = e
                    curr_core_fps[core_fp] = e
            except Exception as ex:
                logger.warning(f"Error fingerprinting current event: {ex}")
                continue
        
        # Detect changes
        added = []
        removed = []
        changed = []
        
        # Find events that exist in current but not in previous
        for fp, event in curr_fps.items():
            if fp not in prev_fps:
                # Check if this is a changed event (same core but different details)
                core_fp = compute_event_core_fingerprint(event)
                if core_fp and core_fp in prev_core_fps:
                    # This is a changed event
                    changed.append((prev_core_fps[core_fp], event))  # (old_event, new_event)
                else:
                    # This is a truly new event
                    added.append(event)
        
        # Find events that exist in previous but not in current
        for fp, event in prev_fps.items():
            if fp not in curr_fps:
                # Check if this event was changed (core exists in current)
                core_fp = compute_event_core_fingerprint(event)
                if core_fp and core_fp in curr_core_fps:
                    # This event was changed, already handled above
                    pass
                else:
                    # This event was truly removed
                    removed.append(event)
        
        # Filter to current week
        added_week = [e for e in added if is_in_current_week(e, today)]
        removed_week = [e for e in removed if is_in_current_week(e, today)]
        # Either side in this week counts, so an event moved out of the week is still announced
        changed_week = [(old, new) for old, new in changed
                        if is_in_current_week(new, today) or is_in_current_week(old, today)]
        
        return added_week, removed_week, changed_week
        
    except Exception as e:
        logger.exception(f"Error detecting event changes: {e}")
        return [], [], []

# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⏰ schedule_daily_posts                                            ║
# ║ Triggers daily and weekly posting tasks at scheduled times        ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=1)
async def schedule_daily_posts(bot):
    task_name = "schedule_daily_posts"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            global _post_state

            # Use utils' timezone-safe function
            local_now = datetime.now(tz=get_local_timezone())
            today = local_now.date()
            if _post_state["date"] != today:
                _post_state = {"date": today, "weekly": set(), "daily": set(), "events": [], "daily_complete": False}
            state = _post_state

            # Posts go out in a 08:00–08:14 window rather than an exact minute, so loop
            # drift can't drop them; the window is short so a restart later in the
            # morning doesn't post a second time (the state lives in memory only).
            # A tag whose calendar fails to fetch is retried each minute; from
            # 08:10 on it is posted with whatever could be fetched.
            in_window = local_now.hour == 8 and local_now.minute < 15
            final_try = local_now.minute >= 10

            # Monday — weekly summaries
            if local_now.weekday() == 0 and in_window:
                monday = get_monday_of_week(today)
                for tag in [t for t in list(GROUPED_CALENDARS) if t not in state["weekly"]]:
                    if await post_tagged_week(bot, tag, monday, allow_partial=final_try):
                        state["weekly"].add(tag)
                    else:
                        logger.warning(f"Weekly post for '{tag}' failed; will retry")
                    # Small delay between posts to avoid rate limits
                    await asyncio.sleep(1)

            # Daily agenda and greeting (from minute 1 so the Monday weekly post goes out first)
            if in_window and local_now.minute >= 1 and not state["daily_complete"]:
                all_done = await post_todays_happenings(bot, include_greeting=True, state=state, allow_partial=final_try)
                if all_done or final_try:
                    state["daily_complete"] = True
                else:
                    logger.warning("Some daily posts failed; will retry")

            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            
            # Add a small delay before the next iteration if we hit an error
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🕵️ watch_for_event_changes                                        ║
# ║ Detects new or removed events in the current week and posts diffs ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=5)
async def watch_for_event_changes(bot):
    task_name = "watch_for_event_changes"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            global _watch_tag_cursor

            today = get_today()
            monday = get_monday_of_week(today)

            # Process at most 3 tags per cycle to avoid overloading, but rotate
            # through them with a persistent cursor so every tag gets checked
            # over successive cycles (a fixed `break` after 3 would starve the rest).
            all_tags = list(GROUPED_CALENDARS.keys())
            if not all_tags:
                update_task_health(task_name, True)
                return

            batch_size = min(3, len(all_tags))
            batch = [all_tags[(_watch_tag_cursor + i) % len(all_tags)] for i in range(batch_size)]
            _watch_tag_cursor = (_watch_tag_cursor + batch_size) % len(all_tags)

            for batch_index, tag in enumerate(batch):
                calendars = GROUPED_CALENDARS.get(tag)
                if not calendars:
                    continue

                # Add small delay between calendar checks to avoid rate limiting
                if batch_index:
                    await asyncio.sleep(2)

                earliest = today - timedelta(days=30)
                latest = today + timedelta(days=90)

                all_events = await _fetch_tag_events(calendars, earliest, latest, context="change detection")
                if not all_events:
                    continue

                # Compare with previous snapshot
                key = f"{tag}_full"
                snapshots = load_previous_events()
                if _needs_baseline(snapshots, tag, calendars):
                    # New tag, failed startup snapshot, or calendars added/removed
                    # (/reload, restart): record silently instead of announcing them
                    _save_baseline(tag, calendars, all_events)
                    logger.info(f"Saved new baseline for '{tag}' ({len(all_events)} events)")
                    continue
                prev_snapshot = snapshots[key]
                
                # Use improved change detection that distinguishes between added/removed/changed
                added_week, removed_week, changed_week = detect_event_changes(prev_snapshot, all_events, today)

                if added_week or removed_week or changed_week:
                    # Instead of immediately posting, queue for verification
                    global _pending_changes
                    
                    current_timestamp = datetime.now()
                    
                    # Check if this tag already has pending changes
                    if tag in _pending_changes:
                        logger.debug(f"Tag '{tag}' already has pending changes, preserving original timestamp")
                        # Keep the original timestamp but update the events
                        existing_data = _pending_changes[tag]
                        _pending_changes[tag] = {
                            'timestamp': existing_data['timestamp'],  # Preserve original timestamp
                            'added_events': added_week,  # Update with latest detected changes
                            'removed_events': removed_week,  # Update with latest detected changes
                            'changed_events': changed_week,  # Update with latest detected changes
                            'verification_count': existing_data.get('verification_count', 0)  # Preserve attempt count
                        }
                        
                        time_elapsed = current_timestamp - existing_data['timestamp']
                        time_remaining = _VERIFICATION_DELAY - time_elapsed
                        logger.debug(f"Updated pending changes for '{tag}', original timer preserved (elapsed: {time_elapsed.total_seconds():.1f}s, remaining: {time_remaining.total_seconds():.1f}s)")
                    else:
                        # New pending change
                        _pending_changes[tag] = {
                            'timestamp': current_timestamp,
                            'added_events': added_week,
                            'removed_events': removed_week,
                            'changed_events': changed_week,
                            'verification_count': 0
                        }
                        logger.debug(f"New pending changes for '{tag}' queued at timestamp: {current_timestamp}")
                    
                    change_summary = f"+{len(added_week)} added" if added_week else ""
                    if change_summary and removed_week:
                        change_summary += ", "
                    if removed_week:
                        change_summary += f"-{len(removed_week)} removed"
                    if change_summary and changed_week:
                        change_summary += ", "
                    if changed_week:
                        change_summary += f"~{len(changed_week)} changed"
                    
                    if tag not in _pending_changes or _pending_changes[tag]['timestamp'] == current_timestamp:
                        logger.info(f"Detected potential changes for '{tag}' ({change_summary}) - queued for verification in {_VERIFICATION_DELAY.total_seconds():.1f} seconds")
                    else:
                        time_elapsed = current_timestamp - _pending_changes[tag]['timestamp']
                        time_remaining = _VERIFICATION_DELAY - time_elapsed
                        logger.info(f"Updated potential changes for '{tag}' ({change_summary}) - verification in {time_remaining.total_seconds():.1f} seconds")
                    
                    # Log some details for debugging (but not too verbose)
                    if len(added_week) <= 3:
                        for event in added_week:
                            title = event.get("summary", "Untitled")[:30] + ("..." if len(event.get("summary", "")) > 30 else "")
                            logger.debug(f"  Added: {title}")
                    else:
                        logger.debug(f"  Added {len(added_week)} events (too many to log individually)")
                        
                    if len(removed_week) <= 3:
                        for event in removed_week:
                            title = event.get("summary", "Untitled")[:30] + ("..." if len(event.get("summary", "")) > 30 else "")
                            logger.debug(f"  Removed: {title}")
                    else:
                        logger.debug(f"  Removed {len(removed_week)} events (too many to log individually)")
                    
                    if len(changed_week) <= 3:
                        for old_event, new_event in changed_week:
                            title = new_event.get("summary", "Untitled")[:30] + ("..." if len(new_event.get("summary", "")) > 30 else "")
                            logger.debug(f"  Changed: {title}")
                    else:
                        logger.debug(f"  Changed {len(changed_week)} events (too many to log individually)")
                    
                else:
                    # Only save if we have data and it differs from previous
                    if all_events and all_events != prev_snapshot:
                        save_current_events_for_key(key, all_events)
                        logger.debug(f"Updated snapshot for '{tag}' with {len(all_events)} events")
                    else:
                        logger.debug(f"No changes for '{tag}'. Snapshot unchanged.")
                        
            # Process any pending verifications
            await process_pending_verifications(bot)
            
            # Debug: Log current pending changes status after processing
            if _pending_changes:
                logger.debug(f"After verification processing, {len(_pending_changes)} changes still pending")
            else:
                logger.debug("No pending changes after verification processing")
                    
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
                "watch_for_event_changes": watch_for_event_changes,
                "verification_watchdog": verification_watchdog,
                "calendar_health_monitor": calendar_health_monitor,
                "check_reminders": check_reminders,
            }
            
            for name, task_func in all_tasks.items():
                # Check error count
                error_count = _task_error_counts.get(name, 0)
                if error_count >= _MAX_CONSECUTIVE_ERRORS:
                    logger.warning(f"Task {name} has {error_count} consecutive errors. Restarting...")
                    if task_func.is_running():
                        task_func.cancel()
                    _task_error_counts[name] = 0
                    _task_locks[name] = False  # Release lock if stuck
                    
                    # Wait a moment before restarting
                    await asyncio.sleep(2)
                    try_start_task(task_func, bot)
                    continue
                    
                # Check for deadlocks (task locked for too long)
                if _task_locks.get(name, False):
                    last_success = _task_last_success.get(name)
                    if last_success and (now - last_success) > _HEALTH_CHECK_INTERVAL:
                        logger.warning(f"Task {name} appears deadlocked. Forcing lock release.")
                        _task_locks[name] = False
                
                # Ensure task is running
                if not task_func.is_running():
                    logger.warning(f"Task {name} is not running. Restarting...")
                    try_start_task(task_func, bot)
                    
            # Self-update health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            # Don't update own health to avoid self-restarting logic

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📜 post_todays_happenings                                          ║
# ║ Posts all events for today and an optional greeting and image     ║
# ╚════════════════════════════════════════════════════════════════════╝
async def post_todays_happenings(bot, include_greeting: bool = False, state: dict | None = None,
                                 allow_partial: bool = True) -> bool:
    """Post today's events per tag, then the greeting once every tag is done
    (or allow_partial). *state* ({"daily": done tags, "events": posted events})
    carries progress across scheduler retries. Returns True when every tag is done."""
    try:
        today = get_today()
        if state is None:
            state = {"daily": set(), "events": []}
        error_count = 0

        # Post events for each tag not done yet
        for i, tag in enumerate([t for t in list(GROUPED_CALENDARS) if t not in state["daily"]]):
            try:
                # Add small delay between posts to avoid rate limiting
                if i:
                    await asyncio.sleep(1)
                # Reuse the posted events for the greeting instead of re-fetching
                # On Mondays the week post already lists today, so only collect the events
                posted_events = await post_tagged_events(bot, tag, today, allow_partial=allow_partial,
                                                         send=tag not in state.get("weekly", ()))
                if posted_events is not None:
                    state["daily"].add(tag)
                    state["events"] += posted_events
            except Exception as e:
                error_count += 1
                state["daily"].add(tag)  # a bug, not an outage: retrying won't help
                logger.exception(f"Error posting events for tag {tag}: {e}")

        all_done = all(t in state["daily"] for t in GROUPED_CALENDARS)
        all_events_for_greeting = state["events"]

        # Generate and post greeting if requested
        if include_greeting and (all_done or allow_partial) and (all_events_for_greeting or not GROUPED_CALENDARS):
            retry_count = 0
            max_retries = 2
            
            # Check if AI is enabled before attempting generation
            if not AI_TOGGLE:
                logger.info("AI features disabled via AI_TOGGLE. Skipping greeting generation.")
                return all_done
                
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
                        try:
                            await send_embed(
                                bot,
                                title=f"The Morning Proclamation 📜 — {persona}",
                                description=greeting,
                                color=0xffe4b5,
                                image_path=image_path
                            )
                        finally:
                            # Discord keeps the uploaded copy; without this /data/art grows ~2 MB a day forever
                            if image_path and os.path.exists(image_path):
                                os.remove(image_path)
                    break  # Success, exit retry loop
                    
                except asyncio.TimeoutError:
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.debug(f"Greeting generation timed out, retrying ({retry_count}/{max_retries})")
                        await asyncio.sleep(2)
                    else:
                        logger.error("Max retries reached for greeting generation")
                except Exception as e:
                    logger.exception(f"Error generating or posting greeting: {e}")
                    break  # Don't retry on general errors
                    
        # Log error summary 
        if error_count > 0:
            logger.warning(f"Daily posts completed with {error_count} errors")
        return all_done
    except Exception as e:
        logger.exception(f"Error in post_todays_happenings: {e}")
        return True  # a bug, not an outage: retrying won't help


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧊 initialize_event_snapshots                                      ║
# ║ Saves a baseline snapshot of all upcoming events across calendars ║
# ╚════════════════════════════════════════════════════════════════════╝
async def initialize_event_snapshots():
    try:
        logger.info("Performing initial silent snapshot of all calendars...")
        today = get_today()
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)

        # Existing snapshots are kept: they survive restarts on purpose, so changes
        # pending at shutdown or made while the bot was down are still announced.
        # Only tags without one, or whose calendar list changed, get a silent baseline.
        existing = load_previous_events()
        failed = 0
        missing = [(t, c) for t, c in list(GROUPED_CALENDARS.items()) if _needs_baseline(existing, t, c)]
        # Process tags sequentially to avoid overloading APIs
        for i, (tag, calendars) in enumerate(missing):
            if i:
                await asyncio.sleep(2)
            all_events = await _fetch_tag_events(calendars, earliest, latest, context="initialization")
            if all_events is None:
                # Keep any older snapshot rather than saving a partial one
                failed += 1
                continue
            _save_baseline(tag, calendars, all_events)
            logger.debug(f"Initial snapshot saved for '{tag}' with {len(all_events)} events")

        status = "complete" if failed == 0 else f"partial (failed tags: {failed})"
        logger.info(f"Initial snapshot {status}.")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception(f"Error in initialize_event_snapshots: {e}")

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 verify_changes                                                  ║
# ║ Re-checks a calendar to verify that detected changes are genuine  ║
# ╚════════════════════════════════════════════════════════════════════╝
async def verify_changes(tag: str, calendars: list, original_added: list, original_removed: list, original_changed: list = None) -> tuple:
    """
    Re-check the calendar to verify if the detected changes are still present.
    Returns (verified_added, verified_removed, verified_changed) with only the changes that are confirmed.
    """
    try:
        if original_changed is None:
            original_changed = []
            
        logger.info(f"VERIFY_CHANGES: Starting verification for tag '{tag}' with {len(original_added)} originally added, {len(original_removed)} originally removed, and {len(original_changed)} originally changed events")
        
        today = get_today()
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)
        
        current_events = await _fetch_tag_events(calendars, earliest, latest, context="verification")
        if not current_events:
            logger.warning(f"No events (or a failed source) during verification for tag '{tag}'; will re-detect next cycle")
            return [], [], []
        
        # Get previous snapshot for comparison
        key = f"{tag}_full"
        prev_snapshot = load_previous_events().get(key, [])
        
        # Use the improved change detection for verification
        verified_added_week, verified_removed_week, verified_changed_week = detect_event_changes(prev_snapshot, current_events, today)
        
        # Compare with original detections to see what's still consistent
        
        # For added events: only include events that are still detected as added
        original_added_fps = {compute_event_fingerprint(e): e for e in original_added if compute_event_fingerprint(e)}
        verified_added_fps = {compute_event_fingerprint(e): e for e in verified_added_week if compute_event_fingerprint(e)}
        consistent_added = [e for fp, e in verified_added_fps.items() if fp in original_added_fps]
        
        # For removed events: only include events that are still detected as removed
        original_removed_fps = {compute_event_fingerprint(e): e for e in original_removed if compute_event_fingerprint(e)}
        verified_removed_fps = {compute_event_fingerprint(e): e for e in verified_removed_week if compute_event_fingerprint(e)}
        consistent_removed = [e for fp, e in verified_removed_fps.items() if fp in original_removed_fps]
        
        # For changed events: verify that the changes are still detected
        consistent_changed = []
        if original_changed:
            # Create a mapping of core fingerprints for original changed events
            original_changed_core_fps = {}
            for old_event, new_event in original_changed:
                core_fp = compute_event_core_fingerprint(new_event)
                if core_fp:
                    original_changed_core_fps[core_fp] = (old_event, new_event)
            
            # Check if the verified changed events match the original ones
            for old_event, new_event in verified_changed_week:
                core_fp = compute_event_core_fingerprint(new_event)
                if core_fp and core_fp in original_changed_core_fps:
                    consistent_changed.append((old_event, new_event))
        
        # Log verification results
        original_count = len(original_added) + len(original_removed) + len(original_changed)
        verified_count = len(consistent_added) + len(consistent_removed) + len(consistent_changed)
        
        if verified_count != original_count:
            logger.info(f"Verification adjusted changes for '{tag}': {original_count} -> {verified_count} changes")
            if len(consistent_added) != len(original_added):
                logger.debug(f"  Added events: {len(original_added)} -> {len(consistent_added)}")
            if len(consistent_removed) != len(original_removed):
                logger.debug(f"  Removed events: {len(original_removed)} -> {len(consistent_removed)}")
            if len(consistent_changed) != len(original_changed):
                logger.debug(f"  Changed events: {len(original_changed)} -> {len(consistent_changed)}")
        elif verified_count == original_count and verified_count > 0:
            logger.debug(f"Verification confirmed all changes for '{tag}': {verified_count} changes")
        
        return consistent_added, consistent_removed, consistent_changed
        
    except Exception as e:
        logger.exception(f"Error during change verification for tag '{tag}': {e}")
        # On verification error, return empty lists to be safe (don't post potentially false changes)
        return [], [], []


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📋 process_pending_verifications                                    ║
# ║ Checks and processes changes that are pending verification         ║
# ╚════════════════════════════════════════════════════════════════════╝
async def process_pending_verifications(bot):
    """Process changes that are pending verification."""
    global _pending_changes
    
    if not _pending_changes:
        return  # No pending changes to process
    
    current_time = datetime.now()
    
    # Create a copy of the keys to avoid modification during iteration
    pending_tags = list(_pending_changes.keys())
    
    # Debug: Log pending changes status
    if _pending_changes:
        logger.debug(f"Checking {len(pending_tags)} pending changes for verification")
        for tag in pending_tags:
            if tag not in _pending_changes:  # Tag may have been removed by another process
                continue
                
            change_data = _pending_changes[tag]
            time_elapsed = current_time - change_data['timestamp']
            time_remaining = _VERIFICATION_DELAY - time_elapsed
            is_ready = time_elapsed >= _VERIFICATION_DELAY
            
            logger.debug(f"  {tag}: queued_at={change_data['timestamp'].strftime('%H:%M:%S')}, elapsed={time_elapsed.total_seconds():.1f}s, remaining={time_remaining.total_seconds():.1f}s, ready={is_ready}")
            
            if is_ready:
                logger.info(f"Tag '{tag}' is ready for verification (waited {time_elapsed.total_seconds():.1f} seconds)")
                await process_single_verification(bot, tag)

async def process_single_verification(bot, tag: str):
    """Process verification for a single tag."""
    # Pop up front: the watch loop and the watchdog both run verifications, and a
    # tag left in _pending_changes during the fetch could be verified (and posted) twice
    change_data = _pending_changes.pop(tag, None)
    if change_data is None:
        return

    logger.info(f"Starting verification process for tag '{tag}'")
    try:
        calendars = GROUPED_CALENDARS.get(tag, [])
        if not calendars:
            logger.warning(f"No calendars found for tag '{tag}' during verification")
            return

        verified_added, verified_removed, verified_changed = await verify_changes(
            tag, calendars, change_data['added_events'], change_data['removed_events'], change_data.get('changed_events', [])
        )
        logger.debug(f"Verification complete for tag '{tag}': {len(verified_added)} verified added, {len(verified_removed)} verified removed, {len(verified_changed)} verified changed")

        if not (verified_added or verified_removed or verified_changed):
            logger.info(f"No verified changes for '{tag}' - original detection was false positive")
            return

        description, color_hint = format_change_lines(verified_added, verified_removed, verified_changed)
        sent = await send_embed(
            bot,
            title=f"📣 {get_name_for_tag(tag)} — calendar changes",
            description=description,
            color=color_hint,
        )
        if not sent:
            # Snapshot untouched, so the next watch cycle re-detects and re-posts
            logger.warning(f"Could not post changes for '{tag}'; will retry on next detection")
            return
        logger.info(f"Posted verified changes for '{tag}': {len(verified_added)} added, {len(verified_removed)} removed, {len(verified_changed)} changed")

        # Apply only what was posted: anything that changed since detection
        # stays a diff and is announced next cycle instead of being absorbed
        key = f"{tag}_full"
        prev = load_previous_events().get(key, [])
        save_current_events_for_key(key, apply_changes(prev, verified_added, verified_removed, verified_changed))

    except Exception as e:
        logger.exception(f"Error processing pending verification for tag '{tag}': {e}")
        attempts = change_data.get('verification_count', 0) + 1
        if attempts >= _MAX_VERIFICATION_ATTEMPTS:
            logger.warning(f"Max verification attempts reached for tag '{tag}', discarding changes")
        else:
            # Re-queue for another attempt unless a newer detection already replaced it
            _pending_changes.setdefault(tag, {**change_data, 'verification_count': attempts})

def apply_changes(snapshot: list, added: list, removed: list, changed: list) -> list:
    """Return snapshot with the given added/removed/changed events applied."""
    drop = {compute_event_fingerprint(e) for e in removed}
    drop |= {compute_event_fingerprint(old) for old, _ in changed}
    kept = [e for e in snapshot if compute_event_fingerprint(e) not in drop]
    return sorted(kept + list(added) + [new for _, new in changed], key=_event_start_key)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 verification_watchdog                                           ║
# ║ Dedicated task to ensure pending verifications are processed      ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(seconds=30)
async def verification_watchdog(bot):
    """Dedicated task to process pending verifications more frequently."""
    task_name = "verification_watchdog"

    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            global _pending_changes
            
            # Clean up any stale pending changes first
            stale_count = cleanup_stale_pending_changes()
            if stale_count > 0:
                logger.info(f"Cleaned up {stale_count} stale pending changes")
            
            if _pending_changes:
                logger.debug(f"Verification watchdog: checking {len(_pending_changes)} pending changes")
                await process_pending_verifications(bot)
            
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📊 calendar_health_monitor                                         ║
# ║ Periodically logs calendar system health metrics                   ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=30)  # Log health every 30 minutes
async def calendar_health_monitor(bot):
    """Monitor and log calendar system health metrics."""
    task_name = "calendar_health_monitor"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            # Import here to avoid circular imports
            from calendar_health import log_health_status, get_health_summary
            
            # Log current health status
            log_health_status()
            
            # Get health summary and log critical alerts
            health = get_health_summary()
            critical_alerts = [a for a in health['alerts'] if a['level'] == 'critical']
            
            if critical_alerts:
                logger.error(f"Critical calendar health issues detected: {len(critical_alerts)} alerts")
                for alert in critical_alerts:
                    logger.error(f"Critical alert: {alert['message']}")
            
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📊 get_pending_changes_status                                      ║
# ║ Returns status information about pending change verifications      ║
# ╚════════════════════════════════════════════════════════════════════╝
def get_pending_changes_status() -> dict:
    """Get status information about pending change verifications (for debugging)."""
    current_time = datetime.now()
    status = {
        'total_pending': len(_pending_changes),
        'verification_delay_seconds': _VERIFICATION_DELAY.total_seconds(),
        'tags': {}
    }
    
    for tag, change_data in _pending_changes.items():
        time_elapsed = current_time - change_data['timestamp']
        time_remaining = _VERIFICATION_DELAY - time_elapsed
        
        status['tags'][tag] = {
            'added_count': len(change_data['added_events']),
            'removed_count': len(change_data['removed_events']),
            'changed_count': len(change_data.get('changed_events', [])),
            'verification_attempts': change_data['verification_count'],
            'time_elapsed_seconds': time_elapsed.total_seconds(),
            'time_remaining_seconds': max(0, time_remaining.total_seconds()),
            'ready_for_verification': time_elapsed >= _VERIFICATION_DELAY,
            'timestamp': change_data['timestamp'].isoformat()
        }
    
    return status

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧹 cleanup_stale_pending_changes                                   ║
# ║ Removes pending changes that have been stuck for too long         ║
# ╚════════════════════════════════════════════════════════════════════╝
def cleanup_stale_pending_changes():
    """Remove pending changes that have been waiting too long (failsafe)."""
    global _pending_changes
    current_time = datetime.now()
    stale_threshold = timedelta(minutes=10)  # Clean up anything older than 10 minutes
    
    stale_tags = []
    for tag, change_data in _pending_changes.items():
        time_elapsed = current_time - change_data['timestamp']
        if time_elapsed > stale_threshold:
            stale_tags.append(tag)
    
    for tag in stale_tags:
        logger.warning(f"Cleaning up stale pending change for tag '{tag}' (stuck for {(current_time - _pending_changes[tag]['timestamp']).total_seconds():.1f} seconds)")
        del _pending_changes[tag]
    
    return len(stale_tags)

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔔 Personal reminder system                                        ║
# ║ DM users before their events start                                ║
# ╚════════════════════════════════════════════════════════════════════╝

_REMINDERS_PATH = os.path.join(os.getenv("DATA_DIR", "/data"), "reminders.json")
_REMINDERS_FALLBACK = os.path.join(os.path.dirname(__file__), "data", "reminders.json")
_sent_reminders: set[str] = set()  # "user_id:event_id:date" dedup keys, persisted so restarts don't re-DM
_sent_reminders_loaded = False
# tag -> (date, fetched_at, events). shortcut: an event created <5 min before its
# start can miss its reminder; shorten _REMINDER_CACHE_SECONDS if that matters.
_reminder_cache: dict = {}
_REMINDER_CACHE_SECONDS = 300


def _reminders_file() -> str:
    """Return writable reminders path, trying primary then fallback."""
    for path in (_REMINDERS_PATH, _REMINDERS_FALLBACK):
        parent = os.path.dirname(path)
        if parent and os.path.isdir(parent) and os.access(parent, os.W_OK):
            return path
    return _REMINDERS_FALLBACK


def _sent_reminders_file() -> str:
    return os.path.join(os.path.dirname(_reminders_file()), "sent_reminders.json")


def load_reminders() -> dict:
    """Load reminder subscriptions from disk. Returns {user_id_str: {...}}."""
    path = _reminders_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load reminders from {path}: {e}")
        return {}


def save_reminders(data: dict):
    """Persist reminder subscriptions to disk."""
    path = _reminders_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json_atomic(path, data, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save reminders to {path}: {e}")


def set_reminder(user_id: int, minutes_before: int = 15, tags: list[str] | None = None) -> dict:
    """Subscribe *user_id* to DM reminders. Returns the saved entry."""
    data = load_reminders()
    entry = {
        "minutes_before": minutes_before,
        "tags": tags or [],
        "enabled": True,
    }
    data[str(user_id)] = entry
    save_reminders(data)
    return entry


def remove_reminder(user_id: int):
    """Unsubscribe *user_id* from reminders."""
    data = load_reminders()
    data.pop(str(user_id), None)
    save_reminders(data)


@tasks.loop(minutes=1)
async def check_reminders(bot):
    """Send DM reminders to subscribed users for upcoming events."""
    task_name = "check_reminders"

    async with TaskLock(task_name) as acquired:
        if not acquired:
            return

        try:
            reminders = load_reminders()
            if not reminders:
                return

            global _sent_reminders_loaded
            if not _sent_reminders_loaded:
                try:
                    with open(_sent_reminders_file(), encoding="utf-8") as f:
                        _sent_reminders.update(json.load(f))
                except (OSError, ValueError):
                    pass
                _sent_reminders_loaded = True
            sent_before = set(_sent_reminders)

            now = datetime.now(tz=get_local_timezone())
            today = now.date()

            # Fetch each subscribed tag's events ONCE per cycle, then evaluate
            # per user — re-fetching every calendar for every subscriber each
            # minute hammers the sources (and Cloudflare-fronted ICS hosts).
            needed_tags: set = set()
            for prefs in reminders.values():
                if not prefs.get("enabled", True):
                    continue
                needed_tags.update(prefs.get("tags") or GROUPED_CALENDARS.keys())
            needed_tags &= set(GROUPED_CALENDARS.keys())

            # Each tag is fetched at most every 5 min, not every minute, to spare the sources
            events_by_tag: dict = {}
            for tag in needed_tags:
                cached = _reminder_cache.get(tag)
                if cached and cached[0] == today and time.time() - cached[1] < _REMINDER_CACHE_SECONDS:
                    events_by_tag[tag] = cached[2]
                    continue
                tag_events: list = []
                complete = True
                for meta in GROUPED_CALENDARS[tag]:
                    try:
                        events = await asyncio.wait_for(
                            asyncio.to_thread(get_events, meta, today, today),
                            timeout=30,
                        )
                    except Exception:
                        events = None
                    if events is None:
                        complete = False
                        continue
                    tag_events.extend(events)
                if complete:
                    _reminder_cache[tag] = (today, time.time(), tag_events)
                events_by_tag[tag] = tag_events

            for user_id_str, prefs in reminders.items():
                if not prefs.get("enabled", True):
                    continue

                minutes_before = prefs.get("minutes_before", 15)
                sub_tags = prefs.get("tags") or list(GROUPED_CALENDARS.keys())

                for tag in sub_tags:
                    for ev in events_by_tag.get(tag, []):
                        start_str = ev.get("start", {}).get("dateTime", "")
                        if not start_str or "T" not in start_str:
                            continue

                        ev_start = parse_date_string(start_str, get_local_timezone())
                        if ev_start is None:
                            continue

                        delta = (ev_start - now).total_seconds() / 60
                        if 0 < delta <= minutes_before:
                            dedup = f"{user_id_str}:{ev.get('id', '')}:{today}"
                            if dedup in _sent_reminders:
                                continue
                            _sent_reminders.add(dedup)

                            await _send_reminder_dm(
                                bot, int(user_id_str), ev, int(delta)
                            )

            # Prune old dedup keys daily
            today_str = str(today)
            _sent_reminders.difference_update(
                {k for k in _sent_reminders if not k.endswith(today_str)}
            )
            if _sent_reminders != sent_before:
                try:
                    write_json_atomic(_sent_reminders_file(), sorted(_sent_reminders))
                except OSError as e:
                    logger.warning(f"Could not persist sent reminders: {e}")

            update_task_health(task_name, True)
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)


async def _send_reminder_dm(bot, user_id: int, event: dict, minutes_left: int):
    """Send a DM embed to *user_id* about an upcoming event."""
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user is None:
            return

        title = event.get("summary", "Untitled")
        location = event.get("location", "")

        import discord
        from views import extract_video_links
        start = parse_date_string(event.get("start", {}).get("dateTime", ""), get_local_timezone())
        # Discord renders <t:…> in each reader's own time zone and keeps the countdown live
        when = (f"<t:{int(start.timestamp())}:t> · <t:{int(start.timestamp())}:R>" if start
                else f"in {minutes_left} minute{'s' if minutes_left != 1 else ''}")
        embed = discord.Embed(
            title=f"🔔 {shorten(title, 240)}",
            description=f"Starts {when}",
            color=0x3498DB,
        )
        if location:
            embed.add_field(name="📍 Location", value=shorten(location, 1000), inline=False)

        links = extract_video_links(event.get("description", "") or "")
        if links:
            link_text = "\n".join(f"[{label}]({url})" for label, url in links)
            embed.add_field(name="🔗 Join", value=link_text[:1024], inline=False)

        await user.send(embed=embed)
        logger.debug(f"Sent reminder DM to {user_id} for '{title}'")
    except Exception as e:
        logger.debug(f"Could not DM user {user_id}: {e}")
