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
    GROUPED_CALENDARS,
    get_events,
    get_name_for_tag,
    get_color_for_tag,
    load_previous_events,
    save_current_events_for_key,
    compute_event_fingerprint
)
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
_pending_changes = {}  # tag -> {timestamp, added_events, removed_events, verification_count}
_VERIFICATION_DELAY = timedelta(seconds=90)  # Wait 90 seconds before re-checking (avoid exact minute boundary issues)
_MAX_VERIFICATION_ATTEMPTS = 3  # Maximum number of verification attempts

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
        
        # Start health monitoring
        monitor_task_health.start(bot)
        
        logger.info("All scheduled tasks started successfully")
    except Exception as e:
        logger.exception(f"Error starting tasks: {e}")
        
        # Try to start tasks individually
        try_start_task(schedule_daily_posts, bot)
        try_start_task(watch_for_event_changes, bot)
        try_start_task(verification_watchdog, bot)
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
# ║ 🕵️ watch_for_event_changes                                        ║
# ║ Detects new or removed events in the current week and posts diffs ║
# ╚════════════════════════════════════════════════════════════════════╝
@tasks.loop(minutes=1)
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
                    # Instead of immediately posting, queue for verification
                    global _pending_changes
                    
                    # Check if this tag already has pending changes
                    if tag in _pending_changes:
                        logger.debug(f"Tag '{tag}' already has pending changes, updating them")
                    
                    current_timestamp = datetime.now()
                    _pending_changes[tag] = {
                        'timestamp': current_timestamp,
                        'added_events': added_week,
                        'removed_events': removed_week,
                        'verification_count': 0
                    }
                    
                    change_summary = f"+{len(added_week)} added" if added_week else ""
                    if change_summary and removed_week:
                        change_summary += ", "
                    if removed_week:
                        change_summary += f"-{len(removed_week)} removed"
                    
                    logger.info(f"Detected potential changes for '{tag}' ({change_summary}) - queued for verification in {_VERIFICATION_DELAY.total_seconds():.1f} seconds")
                    logger.debug(f"Queued changes for '{tag}' at timestamp: {current_timestamp}, verification due at: {current_timestamp + _VERIFICATION_DELAY}")
                    
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
                    
                else:
                    # Only save if we have data and it differs from previous
                    if all_events and (len(all_events) != len(prev_snapshot)):
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
                "verification_watchdog": verification_watchdog
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
# ║ 📜 post_todays_happenings                                          ║
# ║ Posts all events for today and an optional greeting and image     ║
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
            
            # Check if AI is enabled before attempting generation
            if not AI_TOGGLE:
                logger.info("AI features disabled via AI_TOGGLE. Skipping greeting generation.")
                return # Exit the function early if AI is off
                
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
# ║ 🧊 initialize_event_snapshots                                      ║
# ║ Saves a baseline snapshot of all upcoming events across calendars ║
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
                    save_current_events_for_key(f"{tag}_full", all_events)
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

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔍 verify_changes                                                  ║
# ║ Re-checks a calendar to verify that detected changes are genuine  ║
# ╚════════════════════════════════════════════════════════════════════╝
async def verify_changes(tag: str, calendars: list, original_added: list, original_removed: list) -> tuple:
    """
    Re-check the calendar to verify if the detected changes are still present.
    Returns (verified_added, verified_removed) with only the changes that are confirmed.
    """
    try:
        logger.info(f"VERIFY_CHANGES: Starting verification for tag '{tag}' with {len(original_added)} originally added and {len(original_removed)} originally removed events")
        
        today = get_today()
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)
        
        # Re-fetch current events
        current_events = []
        for meta in calendars:
            try:
                events = await asyncio.to_thread(get_events, meta, earliest, latest)
                current_events += events
            except Exception as e:
                logger.warning(f"Error re-fetching events for verification from {meta['name']}: {e}")
                continue
        
        if not current_events:
            logger.warning(f"No events found during verification for tag '{tag}'")
            return [], []
            
        # Sort events reliably
        current_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
        
        # Get previous snapshot for comparison
        key = f"{tag}_full"
        prev_snapshot = load_previous_events().get(key, [])
        
        # Create fingerprints for verification
        prev_fps = {}
        curr_fps = {}
        
        for e in prev_snapshot:
            try:
                fp = compute_event_fingerprint(e)
                if fp:
                    prev_fps[fp] = e
            except Exception:
                continue
        
        for e in current_events:
            try:
                fp = compute_event_fingerprint(e)
                if fp:
                    curr_fps[fp] = e
            except Exception:
                continue
        
        # Re-determine added and removed events
        verified_added = [e for fp, e in curr_fps.items() if fp not in prev_fps]
        verified_removed = [e for fp, e in prev_fps.items() if fp not in curr_fps]
        
        # Filter to current week
        verified_added_week = [e for e in verified_added if is_in_current_week(e, today)]
        verified_removed_week = [e for e in verified_removed if is_in_current_week(e, today)]
        
        # Compare with original detections to see what's still consistent
        original_added_fps = {compute_event_fingerprint(e): e for e in original_added if compute_event_fingerprint(e)}
        original_removed_fps = {compute_event_fingerprint(e): e for e in original_removed if compute_event_fingerprint(e)}
        
        verified_added_fps = {compute_event_fingerprint(e): e for e in verified_added_week if compute_event_fingerprint(e)}
        verified_removed_fps = {compute_event_fingerprint(e): e for e in verified_removed_week if compute_event_fingerprint(e)}
        
        # Only keep changes that are consistent between original detection and verification
        consistent_added = [e for fp, e in verified_added_fps.items() if fp in original_added_fps]
        consistent_removed = [e for fp, e in verified_removed_fps.items() if fp in original_removed_fps]
        
        # Log verification results
        original_count = len(original_added) + len(original_removed)
        verified_count = len(consistent_added) + len(consistent_removed)
        
        if verified_count < original_count:
            logger.info(f"Verification filtered out false positives for '{tag}': {original_count} -> {verified_count} changes")
        elif verified_count == original_count:
            logger.debug(f"Verification confirmed all changes for '{tag}': {verified_count} changes")
        
        return consistent_added, consistent_removed
        
    except Exception as e:
        logger.exception(f"Error during change verification for tag '{tag}': {e}")
        # On verification error, return empty lists to be safe (don't post potentially false changes)
        return [], []


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
    logger.debug(f"Checking {len(pending_tags)} pending changes for verification")
    for tag in pending_tags:
        if tag not in _pending_changes:  # Tag may have been removed by another process
            continue
            
        change_data = _pending_changes[tag]
        time_elapsed = current_time - change_data['timestamp']
        time_remaining = _VERIFICATION_DELAY - time_elapsed
        is_ready = time_elapsed >= _VERIFICATION_DELAY
        
        logger.debug(f"  {tag}: elapsed={time_elapsed.total_seconds():.1f}s, remaining={time_remaining.total_seconds():.1f}s, ready={is_ready}")
        
        if is_ready:
            logger.info(f"Tag '{tag}' is ready for verification (waited {time_elapsed.total_seconds():.1f} seconds)")
            await process_single_verification(bot, tag)

async def process_single_verification(bot, tag: str):
    """Process verification for a single tag."""
    global _pending_changes
    
    if tag not in _pending_changes:
        logger.warning(f"Tag '{tag}' no longer in pending changes when processing verification")
        return
    
    logger.info(f"Starting verification process for tag '{tag}'")
    try:
        change_data = _pending_changes[tag]
        calendars = GROUPED_CALENDARS.get(tag, [])
        
        if not calendars:
            logger.warning(f"No calendars found for tag '{tag}' during verification")
            del _pending_changes[tag]
            return
        
        logger.debug(f"Calling verify_changes for tag '{tag}' with {len(change_data['added_events'])} added and {len(change_data['removed_events'])} removed events")
        
        # Verify the changes
        verified_added, verified_removed = await verify_changes(
            tag, calendars, change_data['added_events'], change_data['removed_events']
        )
        
        logger.debug(f"Verification complete for tag '{tag}': {len(verified_added)} verified added, {len(verified_removed)} verified removed")
        
        # If changes are verified, post them
        if verified_added or verified_removed:
            try:
                lines = []
                if verified_added:
                    lines.append("**📥 Added Events This Week:**")
                    lines += [f"➕ {format_event(e)}" for e in verified_added]
                if verified_removed:
                    lines.append("**📤 Removed Events This Week:**")
                    lines += [f"➖ {format_event(e)}" for e in verified_removed]

                await send_embed(
                    bot,
                    title=f"📣 Event Changes – {get_name_for_tag(tag)}",
                    description="\n".join(lines),
                    color=get_color_for_tag(tag)
                )
                logger.info(f"Posted verified changes for '{tag}': {len(verified_added)} added, {len(verified_removed)} removed")
                
                # Update the snapshot with current events
                await update_snapshot_after_verification(tag, calendars)
                
            except Exception as e:
                logger.exception(f"Error posting verified changes for tag {tag}: {e}")
        else:
            # No verified changes - were false positives
            logger.info(f"No verified changes for '{tag}' - original detection was false positive")
            
        # Remove from pending changes
        if tag in _pending_changes:
            del _pending_changes[tag]
            
    except Exception as e:
        logger.exception(f"Error processing pending verification for tag '{tag}': {e}")
        
        # Increment verification attempt count
        if tag in _pending_changes:
            change_data = _pending_changes[tag]
            change_data['verification_count'] = change_data.get('verification_count', 0) + 1
            
            # Remove if we've exceeded max attempts
            if change_data['verification_count'] >= _MAX_VERIFICATION_ATTEMPTS:
                logger.warning(f"Max verification attempts reached for tag '{tag}', discarding changes")
                del _pending_changes[tag]

async def update_snapshot_after_verification(tag: str, calendars: list):
    """Update the event snapshot after successful verification."""
    try:
        today = get_today()
        earliest = today - timedelta(days=30)
        latest = today + timedelta(days=90)
        all_events = []
        
        for meta in calendars:
            try:
                events = await asyncio.to_thread(get_events, meta, earliest, latest)
                all_events += events
            except Exception as e:
                logger.warning(f"Error fetching events for snapshot update: {e}")
        
        if all_events:
            all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))
            save_current_events_for_key(f"{tag}_full", all_events)
            logger.debug(f"Updated snapshot for '{tag}' after verification with {len(all_events)} events")
    except Exception as e:
        logger.exception(f"Error updating snapshot after verification for tag '{tag}': {e}")

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
# ║ 🐛 debug_verification_system                                       ║
# ║ Utility function to help debug the verification system            ║
# ╚════════════════════════════════════════════════════════════════════╝
def debug_verification_system():
    """Print debug information about the verification system."""
    status = get_pending_changes_status()
    current_time = datetime.now()
    
    print(f"\n=== Verification System Debug Info ===")
    print(f"Current time: {current_time}")
    print(f"Verification delay: {_VERIFICATION_DELAY.total_seconds()} seconds")
    print(f"Total pending changes: {status['total_pending']}")
    
    if status['tags']:
        for tag, info in status['tags'].items():
            print(f"\nTag: {tag}")
            print(f"  Added: {info['added_count']}, Removed: {info['removed_count']}")
            print(f"  Queued at: {info['timestamp']}")
            print(f"  Elapsed: {info['time_elapsed_seconds']:.1f}s")
            print(f"  Remaining: {info['time_remaining_seconds']:.1f}s")
            print(f"  Ready: {info['ready_for_verification']}")
            print(f"  Attempts: {info['verification_attempts']}")
    else:
        print("No pending changes")
    print("=" * 40)
