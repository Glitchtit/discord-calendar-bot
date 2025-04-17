from .utilities import check_channel_permissions, send_embed as util_send_embed

# Import handlers from the main commands.py file
try:
    from ..commands import (
        handle_daily_command,
        handle_herald_command,
        handle_agenda_command,
        handle_greet_command,
        handle_reload_command,
        handle_who_command,
        handle_setup_command,
        handle_status_command,
        handle_weekly_command,
        handle_clear_command, # Ensure clear handler is imported
        post_tagged_events,
        post_tagged_week,
        send_embed as core_send_embed # Alias to avoid conflict
    )
    
    # Re-export them
    __all__ = [
        'handle_daily_command',
        'handle_herald_command',
        'handle_agenda_command',
        'handle_greet_command',
        'handle_reload_command',
        'handle_who_command',
        'handle_setup_command',
        'handle_status_command',
        'handle_weekly_command',
        'handle_clear_command', # Ensure clear handler is exported
        'post_tagged_events',
        'post_tagged_week',
        'check_channel_permissions',
        'util_send_embed', # Export utility send_embed
        'core_send_embed' # Export core send_embed
    ]

except ImportError as e:
    # Log error if imports fail, helps in debugging
    # Attempt to import logger safely
    try:
        from utils.logging import logger
        logger.error(f"Error importing from bot.commands in bot/commands/__init__.py: {e}")
    except ImportError:
        print(f"[ERROR] Failed to import logger. Error in bot/commands/__init__.py: {e}")
        
    # Define __all__ with at least the utilities to prevent further errors down the line
    __all__ = [
        'check_channel_permissions',
        'util_send_embed'
    ]