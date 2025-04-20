# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        AI FUNCTION RE-EXPORT MODULE                        ║
# ║   Provides backward compatibility for AI helpers (greeting, image)         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

# --- Imports & Re-exports ---
# This module simply re-exports functions from `utils.ai_helpers`
# to maintain compatibility with older parts of the codebase that might
# import directly from `ai.py`.
from utils.ai_helpers import generate_greeting, generate_image
__all__ = ['generate_greeting', 'generate_image']