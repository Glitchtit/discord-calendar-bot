# Discord Bot Package
"""
Discord Calendar Bot - Core Package

This package contains the core functionality for the Discord Calendar Bot,
including configuration, logging, and environment management.
"""

__version__ = "2.0.0"
__author__ = "Discord Calendar Bot Team"

from .environment import *
from .logger import logger

__all__ = [
    'DEBUG', 'DISCORD_BOT_TOKEN', 'ANNOUNCEMENT_CHANNEL_ID', 
    'OPENAI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS', 
    'CALENDAR_SOURCES', 'USER_TAG_MAPPING', 'AI_TOGGLE',
    'logger'
]