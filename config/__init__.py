# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                      CONFIGURATION PACKAGE INITIALIZER                     ║
# ║                                                                            ║
# ║  This package centralizes configuration management for the Calendar Bot.   ║
# ║  It exports key functions and constants related to server-specific         ║
# ║  settings, calendar management, and administrative controls.               ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Exports ---
# Re-export functions and constants from the server_config module
# for easier access throughout the application.
from .server_config import (
    add_calendar,           # Function to add a new calendar to a server's config
    remove_calendar,        # Function to remove a calendar from a server's config
    load_server_config,     # Function to load a specific server's configuration
    load_all_server_configs,# Function to load configurations for all servers
    save_server_config,     # Function to save a server's configuration
    SERVER_CONFIG_DIR,      # Constant: Directory path for server configuration files
    get_all_server_ids,     # Function to retrieve IDs of all configured servers
    add_admin_user,         # Function to add a user to a server's admin list
    remove_admin_user,      # Function to remove a user from a server's admin list
    is_superadmin,          # Function to check if a user is the server owner (superadmin)
    get_admin_user_ids      # Function to get the list of admin user IDs for a server
)
