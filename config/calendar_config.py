"""Handles calendar storage and validation"""
from typing import Dict, List
import os
from pathlib import Path
import json
import logging

# Configure logger
logger = logging.getLogger("calendarbot")

# Get the project base directory for consistent path handling
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')

class CalendarConfig:
    def __init__(self, server_id: int):
        server_data_dir = os.path.join(DATA_DIR, 'servers', str(server_id))
        self.path = Path(os.path.join(server_data_dir, 'calendars.json'))
        self.data = self._load()

    def _load(self) -> List[Dict]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in calendars file: {self.path}")
                return []
            except Exception as e:
                logger.exception(f"Error loading calendars: {e}")
                return []
        return []

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2))
            logger.info(f"Saved calendar configuration to {self.path}")
        except Exception as e:
            logger.exception(f"Error saving calendar configuration: {e}")

    def add_calendar(self, calendar_data: Dict):
        self.data.append(calendar_data)
        self.save()
