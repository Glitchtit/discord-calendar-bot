# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                      CALENDAR CONFIGURATION MODULE                       ║
# ║                                                                            ║
# ║  This module defines basic structures and constants related to calendar    ║
# ║  configuration, primarily focusing on path handling.                       ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Imports ---
from typing import Dict, List, Optional, Union
import os
from pathlib import Path
import json
import logging

# --- Logger Setup ---
# Obtain the logger instance for this module.
logger = logging.getLogger("calendarbot")

# --- Constants ---
# Determine the project's root directory for reliable path construction.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Note: The DATA_DIR variable was previously defined here but has been removed.
# Path logic now relies on functions in server_utils.py or hardcoded paths
# relative to the project structure or Docker volume mounts.
