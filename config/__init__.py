# Package initialization file

from .server_config import (
    add_calendar,
    remove_calendar,
    load_server_config,
    load_all_server_configs,  # Add this line to export the new function
    save_server_config,
    SERVER_CONFIG_DIR,
    get_all_server_ids,
    add_admin_user,
    remove_admin_user,
    is_superadmin,
    get_admin_user_ids
)
