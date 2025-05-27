"""
Configuration management for Discord Calendar Bot.

This module provides centralized configuration loading and validation.
"""

from typing import Dict, Any, Optional
import os
from .environment import *
from .logger import logger

# ╔════════════════════════════════════════════════════════════════════╗
# ║ 📋 Configuration Validation                                        ║
# ╚════════════════════════════════════════════════════════════════════╝

def validate_required_config() -> bool:
    """Validate that all required configuration is present."""
    required_vars = [
        ("DISCORD_BOT_TOKEN", DISCORD_BOT_TOKEN),
        ("ANNOUNCEMENT_CHANNEL_ID", ANNOUNCEMENT_CHANNEL_ID),
        ("CALENDAR_SOURCES", CALENDAR_SOURCES),
    ]
    
    missing_vars = []
    for var_name, var_value in required_vars:
        if not var_value:
            missing_vars.append(var_name)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    return True

def validate_optional_config() -> Dict[str, str]:
    """Validate optional configuration and return warnings."""
    warnings = []
    
    if not OPENAI_API_KEY:
        warnings.append("OPENAI_API_KEY not set - AI features will be disabled")
    
    if not USER_TAG_MAPPING:
        warnings.append("USER_TAG_MAPPING not set - user-specific commands may not work")
    
    if not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
        warnings.append(f"Google service account file not found: {GOOGLE_APPLICATION_CREDENTIALS}")
    
    return warnings

def get_config_summary() -> Dict[str, Any]:
    """Get a summary of current configuration."""
    return {
        "debug_mode": DEBUG,
        "ai_enabled": AI_TOGGLE,
        "discord_token_set": bool(DISCORD_BOT_TOKEN),
        "openai_key_set": bool(OPENAI_API_KEY),
        "announcement_channel": ANNOUNCEMENT_CHANNEL_ID,
        "calendar_sources_count": len(CALENDAR_SOURCES.split(",")) if CALENDAR_SOURCES else 0,
        "user_mappings_count": len(USER_TAG_MAPPING.split(",")) if USER_TAG_MAPPING else 0,
        "google_credentials_exist": os.path.exists(GOOGLE_APPLICATION_CREDENTIALS),
    }

def log_startup_config():
    """Log configuration summary at startup."""
    logger.info("=" * 50)
    logger.info("🔧 Configuration Summary")
    logger.info("=" * 50)
    
    config = get_config_summary()
    logger.info(f"Debug Mode: {config['debug_mode']}")
    logger.info(f"AI Features: {'Enabled' if config['ai_enabled'] else 'Disabled'}")
    logger.info(f"Discord Token: {'✅' if config['discord_token_set'] else '❌'}")
    logger.info(f"OpenAI API Key: {'✅' if config['openai_key_set'] else '❌'}")
    logger.info(f"Announcement Channel: {config['announcement_channel']}")
    logger.info(f"Calendar Sources: {config['calendar_sources_count']} configured")
    logger.info(f"User Mappings: {config['user_mappings_count']} configured")
    logger.info(f"Google Credentials: {'✅' if config['google_credentials_exist'] else '❌'}")
    
    # Log warnings
    warnings = validate_optional_config()
    if warnings:
        logger.warning("Configuration warnings:")
        for warning in warnings:
            logger.warning(f"  - {warning}")
    
    logger.info("=" * 50)