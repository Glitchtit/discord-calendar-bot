"""Handles calendar storage and validation"""
from typing import Dict, List
from pathlib import Path
import json

class CalendarConfig:
    def __init__(self, server_id: int):
        self.path = Path(f'data/servers/{server_id}/calendars.json')
        self.data = self._load()

    def _load(self) -> List[Dict]:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return []

    def save(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))

    def add_calendar(self, calendar_data: Dict):
        self.data.append(calendar_data)
        self.save()
