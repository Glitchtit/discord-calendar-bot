"""
reload.py: Event reload and concurrency control.
"""
from asyncio import Lock
from utils.logging import logger
from datetime import datetime, timedelta
import time
import random
from googleapiclient.errors import HttpError
import requests

reinitialize_lock = Lock()

_API_BACKOFF_RESET = timedelta(minutes=30)
_MAX_API_ERRORS = 10
_api_last_error_time = None
_api_error_count = 0

def retry_api_call(func, *args, max_retries=3, **kwargs):
    global _api_last_error_time, _api_error_count
    from utils.rate_limiter import CALENDAR_API_LIMITER, EVENT_LIST_LIMITER
    rate_limiter = CALENDAR_API_LIMITER
    func_str = str(func)
    if 'list(' in func_str.lower() or 'events()' in func_str:
        rate_limiter = EVENT_LIST_LIMITER
        logger.debug("Using event list rate limiter for API call")
    if _api_last_error_time and _api_error_count >= _MAX_API_ERRORS:
        if datetime.now() - _api_last_error_time > _API_BACKOFF_RESET:
            logger.info("API error count reset after backoff period")
            _api_error_count = 0
        else:
            logger.warning(f"Too many API errors ({_api_error_count}), backing off")
            return None
    if not rate_limiter.consume(tokens=1, wait=True):
        logger.error("Failed to acquire rate limit token - this should not happen with wait=True")
        return None
    last_exception = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            status_code = e.resp.status
            if (status_code == 429):
                backoff = (5 ** attempt) + random.uniform(1, 3)
                logger.warning(f"Rate limit hit ({status_code}), attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
                time.sleep(backoff)
                last_exception = e
                continue
            if status_code < 500 and status_code != 429:
                logger.warning(f"Non-retryable Google API error: {status_code} - {str(e)}")
                _api_error_count += 1
                _api_last_error_time = datetime.now()
                raise
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Retryable Google API error ({status_code}), attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
        except requests.exceptions.RequestException as e:
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.warning(f"Network error in API call, attempt {attempt+1}/{max_retries}, backing off for {backoff:.2f}s: {str(e)}")
            time.sleep(backoff)
            last_exception = e
        except Exception as e:
            logger.exception(f"Unexpected error in API call: {e}")
            _api_error_count += 1
            _api_last_error_time = datetime.now()
            raise
    if last_exception:
        _api_error_count += 1
        _api_last_error_time = datetime.now()
        logger.error(f"All {max_retries} retries failed for API call: {last_exception}")
    return None

async def reinitialize_events():
    async with reinitialize_lock:
        if reinitialize_lock.locked():
            logger.warning("Reinitialize events is already in progress. Skipping duplicate call.")
            return False
        logger.info("Starting reinitialization of events.")
        from bot.tasks import initialize_event_snapshots
        from config.server_config import get_all_server_ids, load_server_config
        logger.info("Reloading calendar configurations for all servers")
        for server_id in get_all_server_ids():
            config = load_server_config(server_id)
            logger.debug(f"Loaded config for server {server_id}: {config}")
        logger.info("Re-initializing event snapshots after configuration change")
        await initialize_event_snapshots()
        logger.info("Reinitialization of events completed.")
        return True

def ensure_calendars_loaded() -> bool:
    from .calendar_loading import GROUPED_CALENDARS, load_calendars_from_server_configs
    import os
    import json
    if not GROUPED_CALENDARS:
        logger.warning("GROUPED_CALENDARS is empty, attempting reload...")
        load_calendars_from_server_configs()
    if GROUPED_CALENDARS:
        logger.debug(f"Calendar data available for {len(GROUPED_CALENDARS)} users")
        return True
    else:
        docker_path = "/data/servers"
        if os.path.exists(docker_path) and os.path.isdir(docker_path):
            logger.info("Attempting direct Docker path scan as last resort")
            try:
                for entry in os.listdir(docker_path):
                    if entry.isdigit():
                        server_id = int(entry)
                        config_path = os.path.join(docker_path, entry, "config.json")
                        if os.path.exists(config_path):
                            try:
                                with open(config_path, 'r', encoding='utf-8') as f:
                                    config = json.load(f)
                                    logger.info(f"Found and loaded config at {config_path}")
                                    calendars = config.get("calendars", [])
                                    for calendar in calendars:
                                        if "user_id" in calendar:
                                            user_id = calendar["user_id"]
                                            if user_id not in GROUPED_CALENDARS:
                                                GROUPED_CALENDARS[user_id] = []
                                            GROUPED_CALENDARS[user_id].append({
                                                "server_id": server_id,
                                                "type": calendar["type"],
                                                "id": calendar["id"],
                                                "name": calendar.get("name", "Unnamed Calendar"),
                                                "user_id": user_id
                                            })
                            except Exception as e:
                                logger.error(f"Error processing {config_path}: {e}")
            except Exception as e:
                logger.error(f"Error scanning Docker path: {e}")
        return bool(GROUPED_CALENDARS)
