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

# ╔════════════════════════════════════════════════════════════════════╗
# ⚠️ Deprecated Variables - Use /setup command instead
# ╚════════════════════════════════════════════════════════════════════╝

CALENDAR_SOURCES: Optional[str] = get_str_env("CALENDAR_SOURCES", None)
"""
DEPRECATED: Use the /setup command in Discord instead.

This variable was previously used to define calendars via comma-separated
string (google:id:TAG or ics:url:TAG), but is now replaced by server-specific
configuration via the /setup command.
"""

USER_TAG_MAPPING: str = get_str_env("USER_TAG_MAPPING", "")
"""
DEPRECATED: Use the /setup command in Discord instead.

This variable was previously used for comma-separated user-to-tag mappings 
(e.g., '123456789:T, 987654321:A'), but is now replaced by server-specific
user mappings created during calendar setup.
"""

# ╔════════════════════════════════════════════════════════════════════╗
# 🧩 Other Configuration
# ╚════════════════════════════════════════════════════════════════════╝

IMAGE_SIZE: str = "1024x1024"
"""
Default image resolution for OpenAI's DALL·E image generation.
"""

COMMAND_PREFIX: str = get_str_env("COMMAND_PREFIX", "!")
"""
Prefix for Discord text-based commands (e.g., !ping).
"""
