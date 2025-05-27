import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from src.core.logger import logger

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔧 Utility Functions                                               ║
# ║ Common helper functions used across the application                ║
# ╚════════════════════════════════════════════════════════════════════╝

def safe_get_nested(data: dict, keys: List[str], default=None):
    """Safely get nested dictionary values."""
    try:
        current = data
        for key in keys:
            current = current[key]
        return current
    except (KeyError, TypeError):
        return default

def format_datetime_for_display(dt_str: str) -> str:
    """Format datetime string for user-friendly display."""
    try:
        # Handle different datetime formats
        if 'T' in dt_str:
            if dt_str.endswith('Z'):
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            else:
                dt = datetime.fromisoformat(dt_str)
            return dt.strftime("%I:%M %p")
        else:
            # Date only
            dt = datetime.fromisoformat(dt_str)
            return "All day"
    except ValueError:
        logger.warning(f"Invalid datetime format: {dt_str}")
        return "Unknown time"

def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to specified length with ellipsis."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

def create_event_hash(event: Dict[str, Any]) -> str:
    """Create a hash for an event based on its key properties."""
    try:
        # Extract key fields for hashing
        summary = event.get('summary', '')
        start = event.get('start', {})
        end = event.get('end', {})
        location = event.get('location', '')
        
        # Normalize datetime fields
        start_str = start.get('dateTime', start.get('date', ''))
        end_str = end.get('dateTime', end.get('date', ''))
        
        # Create hash string
        hash_data = f"{summary}|{start_str}|{end_str}|{location}"
        return hashlib.md5(hash_data.encode('utf-8')).hexdigest()
    except Exception as e:
        logger.warning(f"Error creating event hash: {e}")
        return ""

def ensure_directory_exists(path: str) -> bool:
    """Ensure a directory exists, create if necessary."""
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        return False

def load_json_file(file_path: str, default=None) -> Any:
    """Safely load a JSON file with error handling."""
    if default is None:
        default = {}
    
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in {file_path}: {e}")
    except Exception as e:
        logger.error(f"Error loading {file_path}: {e}")
    
    return default

def save_json_file(file_path: str, data: Any) -> bool:
    """Safely save data to a JSON file."""
    try:
        # Ensure directory exists
        directory = os.path.dirname(file_path)
        if directory and not ensure_directory_exists(directory):
            return False
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {file_path}: {e}")
        return False

def get_date_range(days: int = 7) -> tuple[datetime, datetime]:
    """Get start and end datetime for a date range."""
    start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = start_date + timedelta(days=days)
    return start_date, end_date

def is_today(date_str: str) -> bool:
    """Check if a date string represents today."""
    try:
        if 'T' in date_str:
            event_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        else:
            event_date = datetime.fromisoformat(date_str).date()
        return event_date == datetime.now().date()
    except ValueError:
        return False

def clean_text(text: str) -> str:
    """Clean text for safe display (remove special characters, etc.)."""
    if not text:
        return ""
    
    # Remove or replace problematic characters
    cleaned = text.strip()
    # Remove zero-width characters and other invisible characters
    cleaned = ''.join(char for char in cleaned if ord(char) >= 32 or char in '\n\t')
    return cleaned

def format_user_list(user_ids: List[int], guild) -> str:
    """Format a list of user IDs into readable names."""
    try:
        names = []
        for user_id in user_ids:
            try:
                member = guild.get_member(user_id)
                if member:
                    names.append(member.display_name)
                else:
                    names.append(f"User#{user_id}")
            except Exception:
                names.append(f"User#{user_id}")
        
        if not names:
            return "No users"
        elif len(names) == 1:
            return names[0]
        elif len(names) == 2:
            return f"{names[0]} and {names[1]}"
        else:
            return f"{', '.join(names[:-1])}, and {names[-1]}"
    except Exception as e:
        logger.warning(f"Error formatting user list: {e}")
        return "Unknown users"

def get_file_size_mb(file_path: str) -> float:
    """Get file size in MB."""
    try:
        if os.path.exists(file_path):
            size_bytes = os.path.getsize(file_path)
            return size_bytes / (1024 * 1024)
        return 0.0
    except Exception:
        return 0.0

def cleanup_old_files(directory: str, max_age_days: int = 7, pattern: str = "*") -> int:
    """Clean up old files in a directory. Returns number of files deleted."""
    try:
        import glob
        
        if not os.path.exists(directory):
            return 0
        
        deleted_count = 0
        cutoff_time = datetime.now() - timedelta(days=max_age_days)
        
        pattern_path = os.path.join(directory, pattern)
        for file_path in glob.glob(pattern_path):
            try:
                if os.path.isfile(file_path):
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff_time:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.debug(f"Deleted old file: {file_path}")
            except Exception as e:
                logger.warning(f"Error deleting file {file_path}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old files from {directory}")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error during cleanup of {directory}: {e}")
        return 0