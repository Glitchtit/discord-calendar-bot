"""Handles calendar storage and validation"""
from typing import Dict, List, Optional, Union
import os
from pathlib import Path
import json
import logging

# Configure logger
logger = logging.getLogger("calendarbot")

# Get the project base directory for consistent path handling
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')

# Removed the CalendarConfig class and all references to calendars.json as it is no longer used.
