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

class CalendarConfig:
    def __init__(self, server_id: int):
        server_data_dir = os.path.join(DATA_DIR, 'servers', str(server_id))
        self.path = Path(os.path.join(server_data_dir, 'calendars.json'))
        self.data = self._load()
        self.server_id = server_id

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

    def save(self) -> bool:
        """
        Save calendar configuration to disk.
        
        Returns:
            bool: True if save was successful, False otherwise
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2))
            logger.info(f"Saved calendar configuration to {self.path}")
            return True
        except Exception as e:
            logger.exception(f"Error saving calendar configuration: {e}")
            return False

    def add_calendar(self, calendar_data: Dict) -> bool:
        """
        Add a calendar to the configuration.
        
        Args:
            calendar_data: Dictionary with calendar details
            
        Returns:
            bool: True if added successfully, False otherwise
        """
        # Add server ID if not present
        if "server_id" not in calendar_data:
            calendar_data["server_id"] = self.server_id
            
        # Check for duplicates
        for cal in self.data:
            if cal.get("id") == calendar_data.get("id"):
                logger.warning(f"Calendar {calendar_data.get('id')} already exists for server {self.server_id}")
                return False
                
        self.data.append(calendar_data)
        return self.save()
        
    def remove_calendar(self, calendar_id: str) -> bool:
        """
        Remove a calendar from the configuration.
        
        Args:
            calendar_id: ID of the calendar to remove
            
        Returns:
            bool: True if removed successfully, False if not found or save failed
        """
        initial_count = len(self.data)
        self.data = [cal for cal in self.data if cal.get("id") != calendar_id]
        
        if len(self.data) < initial_count:
            logger.info(f"Removing calendar {calendar_id} from server {self.server_id}")
            return self.save()
        else:
            logger.warning(f"Calendar {calendar_id} not found for server {self.server_id}")
            return False
            
    def update_calendar(self, calendar_id: str, updates: Dict) -> bool:
        """
        Update an existing calendar with new values.
        
        Args:
            calendar_id: ID of the calendar to update
            updates: Dictionary of fields to update
            
        Returns:
            bool: True if updated successfully, False if not found or save failed
        """
        for i, cal in enumerate(self.data):
            if cal.get("id") == calendar_id:
                # Update the dictionary with new values
                self.data[i].update(updates)
                logger.info(f"Updated calendar {calendar_id} for server {self.server_id}")
                return self.save()
                
        logger.warning(f"Calendar {calendar_id} not found for server {self.server_id}")
        return False
        
    def get_calendar(self, calendar_id: str) -> Optional[Dict]:
        """
        Get a specific calendar by ID.
        
        Args:
            calendar_id: ID of the calendar to find
            
        Returns:
            Dict or None: Calendar configuration if found, None otherwise
        """
        for cal in self.data:
            if cal.get("id") == calendar_id:
                return cal
        return None
        
    def get_calendars_for_user(self, user_id: Union[str, int]) -> List[Dict]:
        """
        Get all calendars assigned to a specific user.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            List of calendar configurations
        """
        user_id = str(user_id)  # Ensure consistent type for comparison
        return [cal for cal in self.data if str(cal.get("user_id")) == user_id]
