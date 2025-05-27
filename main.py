#!/usr/bin/env python3
"""
Discord Calendar Bot - Main Entry Point

A Discord bot that integrates with Google Calendar and ICS feeds to provide
automated calendar announcements and user interactions.
"""

import sys
import signal
import asyncio
from src.core.logger import logger
from src.core.environment import DISCORD_BOT_TOKEN

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    sys.exit(0)

def main():
    """Main application entry point."""
    try:
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info("=" * 60)
        logger.info("🏰 Discord Calendar Bot Starting")
        logger.info("=" * 60)
        
        # Validate environment
        if not DISCORD_BOT_TOKEN:
            logger.error("❌ DISCORD_BOT_TOKEN environment variable is required")
            logger.error("Please set your Discord bot token and try again.")
            sys.exit(1)
        
        # Import and run the bot
        from bot import main as bot_main
        asyncio.run(bot_main())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error starting bot: {e}")
        sys.exit(1)
    finally:
        logger.info("🏰 Discord Calendar Bot Shutdown Complete")

if __name__ == "__main__":
    main()
