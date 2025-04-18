# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                        AI FUNCTION RE-EXPORT MODULE                        ║
# ║   Provides backward compatibility for AI helpers (greeting, image)         ║
# ╚════════════════════════════════════════════════════════════════════════════╝

from utils.ai_helpers import generate_greeting, generate_image
__all__ = ['generate_greeting', 'generate_image']