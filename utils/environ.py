# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                       ENVIRONMENT CONFIGURATION                            ║
# ║    Centralized access and type conversion for environment variables.       ║
# ║       Includes helpers for boolean, integer, and string values.            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Standard library imports
import os
from pathlib import Path
from typing import Optional

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ HELPER FUNCTIONS                                                           ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- get_bool_env ---
# Retrieves an environment variable and interprets it as a boolean.
# Considers '1', 'true', 'yes' (case-insensitive) as True.
# Args:
#     var_name: The name of the environment variable.
#     default: The default boolean value if the variable is not set.
# Returns: The boolean value of the environment variable or the default.
def get_bool_env(var_name: str, default: bool = False) -> bool:
    val = os.getenv(var_name, str(default)).lower()
    return val in ("1", "true", "yes")

# --- get_int_env ---
# Retrieves an environment variable and converts it to an integer.
# Args:
#     var_name: The name of the environment variable.
#     default: The default integer value if the variable is not set or invalid.
# Returns: The integer value of the environment variable or the default.
def get_int_env(var_name: str, default: int = 0) -> int:
    val_str = os.getenv(var_name)
    if val_str is None:
        return default
    try:
        return int(val_str)
    except ValueError:
        return default

# --- get_str_env ---
# Retrieves an environment variable as a string.
# Args:
#     var_name: The name of the environment variable.
#     default: The default string value if the variable is not set.
# Returns: The string value of the environment variable or the default.
def get_str_env(var_name: str, default: str = "") -> str:
    return os.getenv(var_name, default)

# --- get_default_service_account_path ---
# Determines the default path for the Google service account JSON file.
# Checks potential locations in order: Docker volume, project root, current directory.
# Returns: A string representing the determined file path.
def get_default_service_account_path() -> str:
    docker_path = "/app/service_account.json"
    if os.path.exists(docker_path):
        return docker_path
    project_root = Path(__file__).resolve().parent.parent
    local_path = project_root / "service_account.json"
    if local_path.exists():
        return str(local_path)
    return "./service_account.json"

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ CORE CONFIGURATION VARIABLES                                               ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Debug mode flag (controls verbose logging, etc.)
DEBUG: bool = get_bool_env("DEBUG", False)

# Discord Bot Token (required for Discord API authentication)
DISCORD_BOT_TOKEN: Optional[str] = get_str_env("DISCORD_BOT_TOKEN", None)

# OpenAI API Key (required for AI features like greetings and images)
OPENAI_API_KEY: Optional[str] = get_str_env("OPENAI_API_KEY", None)

# Google Application Credentials Path (path to service account JSON for Google Calendar API)
# Auto-detects path if not explicitly set via environment variable.
GOOGLE_APPLICATION_CREDENTIALS: str = get_str_env(
    "GOOGLE_APPLICATION_CREDENTIALS", get_default_service_account_path()
)

# ╔════════════════════════════════════════════════════════════════════════════╗
# ║ ADDITIONAL CONFIGURATION VARIABLES                                         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# Default image size for DALL-E generation
IMAGE_SIZE: str = "1024x1024"

# Command prefix for legacy text commands (e.g., '!')
COMMAND_PREFIX: str = get_str_env("COMMAND_PREFIX", "!")