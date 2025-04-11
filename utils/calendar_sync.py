"""
calendar_sync.py: Handles real-time calendar update subscriptions and push notifications

This module implements subscription management for calendar updates, allowing
the bot to receive real-time notifications when events change, rather than
constantly polling for updates.
"""

import asyncio
import aiohttp
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from utils.logging import logger
from utils.rate_limiter import CALENDAR_API_LIMITER
from bot.events import service, retry_api_call

# Global subscription tracker
_active_subscriptions = {}
_subscription_renewal_tasks = {}

async def initialize_subscriptions():
    """Initialize calendar subscriptions during bot startup"""
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

async def subscribe_calendar(calendar_data: Dict) -> bool:
    """
    Subscribe to real-time updates for a calendar.
    
    Args:
        calendar_data: Calendar data dictionary with type, id, etc.
        
    Returns:
        bool: True if subscription was successful
    """
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
        
        # With a webhook URL, we could set up push notifications (requires public endpoint)
        # Code for setting up push notifications would go here
        
        return False
        
    except HttpError as e:
        status_code = e.resp.status
        logger.error(f"Google API error ({status_code}) subscribing to {calendar_id}: {e}")
        return False
        
    except Exception as e:
        logger.exception(f"Error subscribing to calendar {calendar_id}: {e}")
        return False

async def unsubscribe_calendar(calendar_data: Dict) -> bool:
    """
    Unsubscribe from real-time updates for a calendar.
    
    Args:
        calendar_data: Calendar data dictionary
        
    Returns:
        bool: True if unsubscription was successful
    """
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
                # Code for stopping webhook subscription would go here
                pass
            
            logger.info(f"Unsubscribed from calendar {calendar_id}")
            return True
        
        # Nothing to unsubscribe if not in our tracking
        return True
        
    except Exception as e:
        logger.exception(f"Error unsubscribing from calendar {calendar_id}: {e}")
        return False

async def handle_webhook_notification(request_data: Dict) -> bool:
    """
    Handle a webhook notification from Google Calendar API.
    
    Args:
        request_data: Webhook notification data
        
    Returns:
        bool: True if processed successfully
    """
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

async def process_calendar_changes(calendar_id: str) -> None:
    """
    Process changes for a calendar after receiving a notification.
    
    Args:
        calendar_id: ID of the calendar with changes
    """
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
            
        # Trigger a calendar update
        from bot.events import reinitialize_events
        await reinitialize_events()
        
        # Update last sync time
        subscription["last_sync"] = datetime.now()
        
    except Exception as e:
        logger.exception(f"Error processing calendar changes for {calendar_id}: {e}")