"""
environ.py: Environment Configuration Loader
Centralized access to critical environment variables with type hints
and helper functions for parsing.
"""

import os
import pathlib
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

OPENAI_API_KEY: Optional[str] = get_str_env("OPENAI_API_KEY", None)
"""
OpenAI API key for generating greeting text and images. 
If unset, AI features may be disabled or fail.
"""

# Determine platform-appropriate default path for Google service account
def get_default_service_account_path() -> str:
    """Provide a platform-appropriate default path for service account"""
    # First, check if we're running in Docker
    if os.path.exists("/app/service_account.json"):
        return "/app/service_account.json"
    
    # Otherwise, try a path relative to this file
    base_dir = pathlib.Path(__file__).resolve().parent.parent
    local_service_account = base_dir / "service_account.json"
    if local_service_account.exists():
        return str(local_service_account)
        
    # Last resort: use a filename in the current directory
    return "./service_account.json"

GOOGLE_APPLICATION_CREDENTIALS: str = get_str_env("GOOGLE_APPLICATION_CREDENTIALS", get_default_service_account_path())
"""
Path to the Google service account JSON used for Calendar API calls.
This will use the environment variable if set, or try to find the file:
1. In the Docker container at /app/service_account.json
2. In the project root directory
3. In the current working directory
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
