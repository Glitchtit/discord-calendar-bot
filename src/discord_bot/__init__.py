# Discord Bot Package
"""
Discord Calendar Bot - Discord Bot Package

This package contains Discord-specific functionality including:
- Slash command handlers and user interactions
- Rich embed creation for calendar displays
- Discord API integration and event handling
"""

from .commands import setup_commands
from .embeds import create_events_embed, create_announcement_embed

__all__ = [
    'setup_commands',
    'create_events_embed', 'create_announcement_embed'
]