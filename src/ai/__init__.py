# AI Package
"""
Discord Calendar Bot - AI Package

This package contains AI-powered functionality including:
- OpenAI-based event title parsing and simplification
- Greeting generation with medieval personas
- DALL-E image generation for announcements
"""

from .title_parser import simplify_event_title, clear_title_cache
from .generator import generate_greeting, generate_image

__all__ = [
    'simplify_event_title', 'clear_title_cache',
    'generate_greeting', 'generate_image'
]