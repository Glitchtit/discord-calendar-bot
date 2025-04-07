"""
environ.py: Environment Configuration Loader
Centralized access to critical environment variables with type hints
and helper functions for parsing.
"""

import os
from typing import Optional


def get_bool_env(var_name: str, default: bool = False) -> bool:
    """
    Retrieves an environment variable as a boolean.

    Args:
        var_name: Name of the environment variable to fetch.
        default: Fallback boolean if the variable is not set.

    Returns:
        True or False, based on the environment variable value.
        The environment variable is considered 'true' if it is
        '1', 'true', or 'yes' (case-insensitive).
    """
    val = os.getenv(var_name, str(default)).lower()
    return val in ("1", "true", "yes")


def get_int_env(var_name: str, default: int = 0) -> int:
    """
    Retrieves an environment variable as an integer.

    Args:
        var_name: Name of the environment variable to fetch.
        default: Fallback integer if the variable is not set or invalid.

    Returns:
        The integer value of the environment variable, or 'default' if
        parsing fails or the variable is unset.
    """
    val_str = os.getenv(var_name, None)
    if val_str is None:
        return default
    try:
        return int(val_str)
    except ValueError:
        return default


def get_str_env(var_name: str, default: str = "") -> str:
    """
    Retrieves an environment variable as a string.

    Args:
        var_name: Name of the environment variable to fetch.
        default: Default string to return if variable is not set.

    Returns:
        The environment variable's value, or 'default' if unset.
    """
    return os.getenv(var_name, default)


# ╔════════════════════════════════════════════════════════════════════╗
# 🔧 Core Variables
# ╚════════════════════════════════════════════════════════════════════╝

# Debug mode toggle — enables verbose logging if set to "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Discord bot token — required for authentication with Discord API
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel ID where announcements and embeds will be posted
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "0"))

# OpenAI API key — required for generating greetings and images
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Path to service account JSON for Google Calendar API
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/service_account.json")

# Note: CALENDAR_SOURCES and USER_TAG_MAPPING have been removed
# Server-specific configurations are now stored in /data/servers/<server_id>.json
DEBUG: bool = get_bool_env("DEBUG", False)
"""
Indicates whether to run in debug mode, enabling verbose logging, etc.
"""

DISCORD_BOT_TOKEN: Optional[str] = get_str_env("DISCORD_BOT_TOKEN", None)
"""
Discord bot token — required for authentication with the Discord API.
If unset, the bot will fail at startup.
"""

ANNOUNCEMENT_CHANNEL_ID: int = get_int_env("ANNOUNCEMENT_CHANNEL_ID", 0)
"""
Numeric channel ID where announcements and embeds will be posted.
"""

OPENAI_API_KEY: Optional[str] = get_str_env("OPENAI_API_KEY", None)
"""
OpenAI API key for generating greeting text and images. 
If unset, AI features may be disabled or fail.
"""

GOOGLE_APPLICATION_CREDENTIALS: str = get_str_env("GOOGLE_APPLICATION_CREDENTIALS", "/app/service_account.json")
"""
Path to the Google service account JSON used for Calendar API calls.
"""

CALENDAR_SOURCES: Optional[str] = get_str_env("CALENDAR_SOURCES", None)
"""
Comma-separated string defining calendars to load (google:id:TAG or ics:url:TAG).
"""

USER_TAG_MAPPING: str = get_str_env("USER_TAG_MAPPING", "")
"""
Comma-separated user-to-tag mappings (e.g., '123456789:T, 987654321:A').
"""

IMAGE_SIZE: str = "1024x1024"
"""
Default image resolution for OpenAI's DALL·E image generation.
"""

COMMAND_PREFIX: str = get_str_env("COMMAND_PREFIX", "!")
"""
Prefix for Discord text-based commands (e.g., !ping).
"""
