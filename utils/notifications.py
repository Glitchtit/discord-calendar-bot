# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                           NOTIFICATIONS MODULE                             ║
# ║         System for sending error notifications to admin users              ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set

# Third-party imports
import discord

# Local application imports
from utils.logging import logger
from config.server_config import load_admins

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ GLOBAL VARIABLES                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Dictionary to track recently sent notifications with timestamps
_recent_notifications: Dict[str, datetime] = {}
# Time to wait between duplicate notifications
_notification_cooldown = timedelta(minutes=15)

# Set of admin user IDs that should receive notifications
_admin_user_ids: Set[str] = set()

# Discord client instance (set during initialization)
_discord_client = None

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ INITIALIZATION FUNCTIONS                                                   ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- register_discord_client ---
# Registers the Discord client to be used for sending notifications.
# Args:
#     client: The Discord client instance to register
def register_discord_client(client: discord.Client):
    global _discord_client
    _discord_client = client
    logger.info("Discord client registered for notifications")

# --- register_admin ---
# Adds a single Discord user ID to the set of notification recipients.
# Args:
#     user_id: Discord user ID to register as an admin
def register_admin(user_id: str):
    _admin_user_ids.add(str(user_id))
    logger.debug(f"Registered admin {user_id} for notifications")

# --- register_admins ---
# Registers multiple Discord user IDs as notification recipients.
# Args:
#     user_ids: List of Discord user IDs to register as admins
def register_admins(user_ids: List[str]):
    for user_id in user_ids:
        register_admin(user_id)

# --- register_admins_from_config ---
# Loads admin users from the server configuration and registers them.
# Args:
#     server_id: The Discord server ID to load admins for
def register_admins_from_config(server_id: int):
    admin_ids = load_admins(server_id)
    for user_id in admin_ids:
        register_admin(user_id)
    
# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ NOTIFICATION UTILITIES                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- is_notification_allowed ---
# Determines if a notification can be sent based on cooldown settings.
# Args:
#     notification_key: Unique identifier for this notification type
# Returns: Boolean indicating if notification can be sent
def is_notification_allowed(notification_key: str) -> bool:
    if notification_key in _recent_notifications:
        last_sent = _recent_notifications[notification_key]
        if datetime.now() - last_sent < _notification_cooldown:
            logger.debug(f"Notification '{notification_key}' on cooldown")
            return False
    
    # Update the timestamp and allow sending
    _recent_notifications[notification_key] = datetime.now()
    return True

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ NOTIFICATION FUNCTIONS                                                     ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- notify_admins ---
# Sends an embedded notification to all registered admin users.
# Args:
#     title: Title of the notification
#     message: Main message content
#     severity: One of "info", "warning", "error", or "critical"
#     notification_key: Optional key for cooldown tracking
# Returns: Boolean indicating if any notifications were sent successfully
async def notify_admins(
    title: str, 
    message: str, 
    severity: str = "info",
    notification_key: Optional[str] = None
) -> bool:
    if not _discord_client:
        logger.error("Cannot send notifications: Discord client not registered")
        return False
        
    if not _admin_user_ids:
        logger.warning("No admin users registered for notifications")
        return False
        
    # Use the title as the notification key if none provided
    if notification_key is None:
        notification_key = title.lower().replace(" ", "_")
    
    # Check cooldown for this notification type
    if not is_notification_allowed(notification_key):
        return False
        
    # --- Determine color based on severity ---
    # Map severity levels to Discord embed colors
    colors = {
        "info": 0x3498db,      # Blue
        "warning": 0xf39c12,   # Orange
        "error": 0xe74c3c,     # Red
        "critical": 0x9b59b6   # Purple
    }
    color = colors.get(severity.lower(), colors["info"])
    
    # Create the embed
    embed = discord.Embed(
        title=f"🔔 {title}",
        description=message,
        color=color,
        timestamp=datetime.now()
    )
    
    embed.set_footer(text=f"Calendar Bot | Severity: {severity.upper()}")
    
    # --- Send to all registered admins ---
    # Track how many notifications were successfully sent
    success_count = 0
    for admin_id in _admin_user_ids:
        try:
            user = await _discord_client.fetch_user(int(admin_id))
            if user:
                await user.send(embed=embed)
                success_count += 1
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")
    
    logger.info(f"Sent '{title}' notification to {success_count}/{len(_admin_user_ids)} admins")
    return success_count > 0

# --- notify_critical_error ---
# Sends notification with detailed information about a critical exception.
# Args:
#     error_context: Description of what the bot was doing when error occurred
#     exception: The exception that was raised
# Returns: Boolean indicating if notification was sent
async def notify_critical_error(error_context: str, exception: Exception) -> bool:
    # Generate a unique key for this type of error
    error_type = type(exception).__name__
    notification_key = f"error_{error_type}_{error_context.lower().replace(' ', '_')}"
    
    # Format the error message with exception details
    message = (
        f"**Error Context:** {error_context}\n\n"
        f"**Exception Type:** {error_type}\n"
        f"**Error Message:** {str(exception)}\n\n"
        f"Check the log files for complete details."
    )
    
    return await notify_admins(
        title="Critical Error Detected",
        message=message,
        severity="critical",
        notification_key=notification_key
    )

# --- notify_calendar_issue ---
# Sends notification about problems with calendar access or synchronization.
# Args:
#     calendar_name: Name of the problematic calendar
#     issue: Description of the issue
#     retry_info: Optional information about retry attempts
# Returns: Boolean indicating if notification was sent
async def notify_calendar_issue(calendar_name: str, issue: str, retry_info: str = None) -> bool:
    # Generate a unique key for this calendar issue
    notification_key = f"calendar_issue_{calendar_name.lower().replace(' ', '_')}"
    
    message = f"**Calendar:** {calendar_name}\n**Issue:** {issue}"
    if retry_info:
        message += f"\n\n{retry_info}"
    
    return await notify_admins(
        title="Calendar Access Issue",
        message=message,
        severity="warning",
        notification_key=notification_key
    )