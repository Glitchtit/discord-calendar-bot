"""
ai.py: Re-exports AI functions from utils/ai_helpers.py for backward compatibility.

This file exists to maintain compatibility with existing code that imports 
from ai.py, while the actual implementation has been moved to utils/ai_helpers.py.
"""

from utils.ai_helpers import generate_greeting, generate_image

# Re-export the functions
__all__ = ['generate_greeting', 'generate_image']