# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                           CALENDAR SYNC UTILITIES                          ║
# ║ Handles real-time calendar update subscriptions and push notifications     ║
# ║ (Note: Push notifications require a configured public webhook endpoint).   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import asyncio
import aiohttp
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Third-party imports
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Local application imports
from utils.logging import logger
from utils.rate_limiter import CALENDAR_API_LIMITER
from bot.events import service, retry_api_call # Assuming these exist and are correctly imported

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ GLOBAL STATE AND CONFIGURATION                                             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Dictionary to track active calendar subscriptions {calendar_id: subscription_info}
_active_subscriptions = {}
# Dictionary to track renewal tasks for subscriptions {calendar_id: asyncio.Task}
_subscription_renewal_tasks = {}

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ SUBSCRIPTION MANAGEMENT                                                    ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- initialize_subscriptions ---
# Initializes calendar subscriptions for all configured servers during bot startup.
# Iterates through servers and their calendars, subscribing to Google calendars.
# Returns: True if at least one subscription was successfully initiated, False otherwise.
async def initialize_subscriptions():
    # Import here to avoid circular imports
    from config.server_config import get_all_server_ids, load_server_config
    
    logger.info("Initializing calendar subscriptions...")
    
    subscription_count = 0
    server_count = 0
    
    # For each server, get calendars and subscribe
    for server_id in get_all_server_ids():
        try:
            config = load_server_config(server_id)
            calendars = config.get("calendars", [])
            
            if not calendars:
                continue
                
            server_count += 1
            
            for calendar in calendars:
                # Only Google calendars support push notifications
                if calendar.get("type") == "google":
                    try:
                        # Add server_id to calendar data for reference
                        calendar["server_id"] = server_id
                        success = await subscribe_calendar(calendar)
                        if success:
                            subscription_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to subscribe to calendar {calendar.get('id')}: {e}")
        except Exception as e:
            logger.error(f"Error setting up subscriptions for server {server_id}: {e}")
    
    logger.info(f"Calendar subscription initialization complete. Subscribed to {subscription_count} calendars across {server_count} servers")
    return subscription_count > 0

# --- subscribe_calendar ---
# Subscribes to updates for a specific Google Calendar.
# Currently defaults to polling mode if no webhook URL is configured.
# Args:
#     calendar_data: Dictionary containing calendar details (id, type, server_id).
# Returns: True if subscription (or polling setup) was successful, False otherwise.
async def subscribe_calendar(calendar_data: Dict) -> bool:
    # Only Google calendars support push notifications currently
    if calendar_data.get("type") != "google":
        logger.debug(f"Calendar type {calendar_data.get('type')} doesn't support push notifications")
        return False
    
    calendar_id = calendar_data.get("id")
    
    # Skip if we don't have the Google Calendar API available
    if not service:
        logger.warning(f"Google Calendar service not initialized, can't subscribe to {calendar_id}")
        return False
    
    try:
        # Check if we already have an active subscription for this calendar
        if calendar_id in _active_subscriptions:
            logger.debug(f"Already subscribed to calendar {calendar_id}")
            return True
            
        # Set up webhook (in a real implementation, you'd need to set up a proper webhook endpoint)
        # This is a placeholder implementation - in production you need a public webhook endpoint
        webhook_url = None  # Replace with your actual webhook URL in production
        
        # Without a webhook URL, we'll default to polling mode
        if not webhook_url:
            logger.info(f"No webhook URL configured, using polling mode for calendar {calendar_id}")
            _active_subscriptions[calendar_id] = {
                "mode": "polling",
                "calendar_id": calendar_id,
                "server_id": calendar_data.get("server_id"),
                "last_sync": datetime.now()
            }
            return True
        
        # --- Placeholder for Webhook Setup ---
        # In a production environment with a public endpoint, this section
        # would contain the Google API call to create a watch channel.
        # Example structure (requires actual implementation):
        # watch_request = {
        #     "id": f"sub-{calendar_id}-{int(time.time())}", # Unique ID
        #     "type": "web_hook",
        #     "address": webhook_url,
        #     # "params": { "ttl": "3600" } # Optional: Time-to-live
        # }
        # try:
        #     watch_response = await asyncio.to_thread(
        #         lambda: service.events().watch(calendarId=calendar_id, body=watch_request).execute()
        #     )
        #     _active_subscriptions[calendar_id] = {
        #         "mode": "webhook",
        #         "calendar_id": calendar_id,
        #         "server_id": calendar_data.get("server_id"),
        #         "resource_id": watch_response["resourceId"],
        #         "expiration": datetime.fromtimestamp(int(watch_response["expiration"]) / 1000)
        #     }
        #     logger.info(f"Webhook subscription created for {calendar_id}")
        #     # Schedule renewal task based on expiration
        #     return True
        # except HttpError as e:
        #     logger.error(f"Failed to create webhook for {calendar_id}: {e}")
        #     return False
        
        return False
        
    except HttpError as e:
        status_code = e.resp.status
        logger.error(f"Google API error ({status_code}) subscribing to {calendar_id}: {e}")
        return False
        
    except Exception as e:
        logger.exception(f"Error subscribing to calendar {calendar_id}: {e}")
        return False

# --- unsubscribe_calendar ---
# Unsubscribes from updates for a specific calendar.
# Removes tracking and cancels any associated renewal tasks.
# If using webhooks, would also call the API to stop the channel.
# Args:
#     calendar_data: Dictionary containing calendar details (id).
# Returns: True if unsubscription was successful or not needed, False on error.
async def unsubscribe_calendar(calendar_data: Dict) -> bool:
    calendar_id = calendar_data.get("id")
    
    try:
        # Remove from our tracking
        if calendar_id in _active_subscriptions:
            subscription = _active_subscriptions.pop(calendar_id)
            
            # Cancel any renewal task
            if calendar_id in _subscription_renewal_tasks:
                task = _subscription_renewal_tasks.pop(calendar_id)
                if not task.done() and not task.cancelled():
                    task.cancel()
            
            # If we have a webhook subscription, we would need to stop it
            if subscription.get("mode") == "webhook" and subscription.get("resource_id"):
                # --- Placeholder for Stopping Webhook ---
                # If using webhooks, add the API call here:
                # try:
                #     await asyncio.to_thread(
                #         lambda: service.channels().stop(
                #             body={"id": subscription["id"], "resourceId": subscription["resource_id"]}
                #         ).execute()
                #     )
                #     logger.info(f"Stopped webhook subscription for {calendar_id}")
                # except HttpError as e:
                #     logger.error(f"Failed to stop webhook for {calendar_id}: {e}")
                #     # Continue cleanup even if API call fails
                pass
            
            logger.info(f"Unsubscribed from calendar {calendar_id}")
            return True
        
        # Nothing to unsubscribe if not in our tracking
        return True
        
    except Exception as e:
        logger.exception(f"Error unsubscribing from calendar {calendar_id}: {e}")
        return False

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ NOTIFICATION HANDLING (Placeholder for Webhook Implementation)             ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- handle_webhook_notification ---
# Processes an incoming webhook notification from Google Calendar API.
# (Requires a functional webhook endpoint to receive notifications).
# Identifies the calendar and triggers processing of changes.
# Args:
#     request_data: The data received from the Google Calendar webhook.
# Returns: True if the notification was processed successfully, False otherwise.
async def handle_webhook_notification(request_data: Dict) -> bool:
    try:
        # Extract resource ID and calendar ID
        resource_id = request_data.get("resourceId")
        calendar_id = None
        
        # Find the corresponding calendar ID from our subscriptions
        for cal_id, subscription in _active_subscriptions.items():
            if subscription.get("resource_id") == resource_id:
                calendar_id = cal_id
                break
                
        if not calendar_id:
            logger.warning(f"Received notification for unknown resource ID: {resource_id}")
            return False
            
        # Process the notification based on the state token
        # This would trigger event snapshot updates and notifications
        
        # Schedule a background task to process the changes
        asyncio.create_task(process_calendar_changes(calendar_id))
        
        return True
        
    except Exception as e:
        logger.exception(f"Error processing webhook notification: {e}")
        return False

# --- process_calendar_changes ---
# Fetches and processes updates for a specific calendar after a notification.
# This function would typically involve fetching recent events or using sync tokens.
# Currently triggers a full reinitialization for simplicity.
# Args:
#     calendar_id: The ID of the calendar that has changes.
async def process_calendar_changes(calendar_id: str) -> None:
    try:
        # Retrieve subscription info
        subscription = _active_subscriptions.get(calendar_id)
        if not subscription:
            logger.warning(f"No subscription found for calendar {calendar_id}")
            return
            
        # Get the server ID from the subscription
        server_id = subscription.get("server_id")
        if not server_id:
            logger.warning(f"No server ID associated with calendar {calendar_id}")
            return
            
        # --- Trigger Event Update ---
        # In a more refined system, this might fetch only changed events
        # using sync tokens or query for events updated since the last sync.
        # For now, it triggers a broader reinitialization.
        from bot.events import reinitialize_events
        logger.info(f"Processing changes for calendar {calendar_id} (Server: {server_id})")
        # Consider passing server_id or calendar_id to reinitialize_events
        # if it can handle more targeted updates.
        await reinitialize_events() # Potentially inefficient, reloads all events
        
        # Update last sync time
        subscription["last_sync"] = datetime.now()
        
    except Exception as e:
        logger.exception(f"Error processing calendar changes for {calendar_id}: {e}")