import os
import json
import logging
from threading import Lock
from typing import Dict, Any

logger = logging.getLogger(__name__)
_load_lock = Lock()

def load_server_config(server_id: int) -> Dict[str, Any]:
    """Load server-specific configuration from JSON file."""
    config_path = f"./data/servers/{server_id}.json"
    try:
        with _load_lock:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON in config for server {server_id}")
    except Exception as e:
        logger.exception(f"Config load error for {server_id}: {e}")
    return {"calendars": [], "user_mappings": {}}

def save_server_config(server_id: int, config: Dict[str, Any]):
    """Save updated server configuration to JSON file."""
    config_path = f"./data/servers/{server_id}.json"
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with _load_lock:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
