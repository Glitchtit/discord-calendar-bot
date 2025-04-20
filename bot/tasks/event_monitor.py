# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                   BOT TASKS EVENT MONITOR MODULE                     ║
# ║    Monitors calendars for changes (added/removed events) and notifies    ║
# ║    users. Also handles initial event snapshotting and missed events.     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""
Event change monitoring and notifications.

Monitors calendars for changes and notifies users about added/removed events.
"""
import asyncio
from datetime import datetime, timedelta
from discord.ext import tasks

from utils.logging import logger
from utils import get_today, format_event
from bot.events import (
    GROUPED_CALENDARS,
    load_post_tracking,
    get_events,
    compute_event_fingerprint,
    load_previous_events,
    save_current_events_for_key
)
from config.server_config import get_all_server_ids, load_server_config
from .health import TaskLock, update_task_health
from .utilities import send_embed
from .weekly_posts import is_in_current_week

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EVENT CHANGE MONITORING TASK                                              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- watch_for_event_changes (task loop) ---
# Runs periodically (every minute) to check for changes in calendar events.
# Fetches events within a defined window (-30 to +90 days from today).
# Compares current events (fingerprinted) against the last saved snapshot for each user/tag.
# Identifies added and removed events.
# Notifies the relevant user via DM about changes *within the current week*.
# Saves the updated event snapshot to disk if changes are detected or if the snapshot differs.
# Processes calendars in batches with delays to avoid rate limiting.
# Uses TaskLock for concurrency control and updates task health.
# Args:
#     bot: The discord.py Bot instance.
@tasks.loop(minutes=1)  # Reduced frequency for stability
async def watch_for_event_changes(bot):
    task_name = "watch_for_event_changes"
    
    async with TaskLock(task_name) as acquired:
        if not acquired:
            return
            
        try:
            today = get_today()
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
                
                # Extract user_id and server_id from the first calendar
                # This assumes all calendars in a group share the same user_id and server_id
                if not calendars:
                    continue
                    
                user_id = calendars[0].get('user_id')
                server_id = calendars[0].get('server_id')
                
                if not user_id or not server_id:
                    logger.warning(f"Missing user_id or server_id for tag {tag}. Skipping.")
                    continue

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
                key = f"{user_id}_full"
                prev_snapshot = load_previous_events(server_id).get(key, [])
                
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

                        # Update embed formatting
                        await send_embed(
                            bot,
                            title="📣 Event Changes",
                            description="\n".join(lines),
                            color=0x3498db,  # Default color
                            content=f"<@{user_id}>"  # Mention user in content
                        )
                        logger.info(f"Detected changes for user ID '{user_id}', snapshot updated.")
                        save_current_events_for_key(server_id, f"{user_id}_full", all_events)
                    except Exception as e:
                        logger.exception(f"Error posting changes for user ID '{user_id}']: {e}")
                else:
                    # Only save if we have data and it differs from previous
                    if all_events and (len(all_events) != len(prev_snapshot)):
                        save_current_events_for_key(server_id, f"{user_id}_full", all_events)
                        logger.debug(f"Updated snapshot for user ID '{user_id}' with {len(all_events)} events")
                    else:
                        logger.debug(f"No changes for user ID '{user_id}'. Snapshot unchanged.")
                    
            # Update task health status
            update_task_health(task_name, True)
            
        except Exception as e:
            logger.exception(f"Error in {task_name}: {e}")
            update_task_health(task_name, False)
            
            # Add a small delay before the next iteration if we hit an error
            await asyncio.sleep(5)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ EVENT SNAPSHOT INITIALIZATION                                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- initialize_event_snapshots ---
# Performs an initial, silent fetch and save of all events for all configured calendars.
# This creates the baseline snapshot used by `watch_for_event_changes`.
# Typically run at bot startup or after configuration reloads.
# Fetches events within the standard window (-30 to +90 days).
# Processes calendars sequentially with delays to avoid rate limiting.
# Saves the snapshot for each user/tag.
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
                    save_current_events_for_key(meta["server_id"], f"{tag}_full", [])
                    logger.debug(f"Empty initial snapshot saved for '{tag}'")
            except Exception as e:
                failed += 1
                logger.exception(f"Error initializing snapshot for tag {tag}: {e}")

        status = "complete" if failed == 0 else f"partial (failed: {failed})"
        logger.info(f"Initial snapshot {status}. Processed {processed}/{total_calendars} calendars.")
    except Exception as e:
        logger.exception(f"Error in initialize_event_snapshots: {e}")

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ MISSED EVENT CHECK (POST-DISCONNECTION)                                   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- check_for_missed_events ---
# Checks for events or posts that might have been missed during a bot disconnection.
# Currently focuses on re-running the daily post task if it was missed.
# 1. Re-initializes event snapshots to ensure current data.
# 2. Checks each server's configuration.
# 3. If daily announcements are enabled and it's currently within the typical posting window (e.g., morning),
#    it checks a tracking file to see if today's post was already made.
# 4. If not posted, it triggers `post_todays_happenings` for that server.
# Args:
#     bot: The discord.py Bot instance.
async def check_for_missed_events(bot):
    """
    Checks if any events were missed during disconnection and 
    handles them appropriately.
    """
    try:
        # Get current time and calculate a reasonable window to check
        # (e.g., past 24 hours to account for disconnection period)
        today = get_today()
        yesterday = today - timedelta(days=1)
        
        logger.info(f"Checking for missed events between {yesterday} and {today}")
        
        # Re-snapshot events to ensure we have the latest data
        await initialize_event_snapshots()
        
        # For each server, check if we need to post daily updates
        for server_id in get_all_server_ids():
            config = load_server_config(server_id)
            if not config:
                continue
                
            # Check if daily announcements are enabled and we're in the posting window
            if config.get("daily_announcements_enabled", False):
                current_hour = datetime.now().hour
                # If we're within the announcement window (usually morning)
                if 5 <= current_hour <= 10:
                    try:
                        # Check if we already posted today's events
                        # This requires a new tracking mechanism to avoid duplicate posts
                        tracking = load_post_tracking(server_id)
                        
                        # If we haven't posted today's update yet, do it now
                        if today.isoformat() not in tracking.get("daily_posts", []):
                            logger.info(f"Posting missed daily update for server {server_id}")
                            from .daily_posts import post_todays_happenings
                            await post_todays_happenings(bot, server_id=server_id)
                    except Exception as e:
                        logger.error(f"Error checking/posting missed daily update: {e}")
        
        logger.info("Missed event check completed")
    except Exception as e:
        logger.exception(f"Error in check_for_missed_events: {e}")
