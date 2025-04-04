"""
main.py: Entry point for the Calendar Bot, with improved error handling,
environment validation, and type hints.
"""

import asyncio
import signal
from typing import Any

from log import logger
from tasks import start_background_tasks
from bot import bot


async def start() -> None:
    """
    Initiates the bot, starts background tasks, and handles any exceptions
    during startup or runtime.
    """
    logger.info("[main.py] 🎬 Starting calendar bot...")

    # Start scheduled tasks (daily/weekly posts, snapshots, etc.)
    start_background_tasks(bot)

    try:
        await bot.start(bot_token())
    except Exception as e:
        logger.exception("[main.py] ❌ Bot crashed during startup or runtime.", exc_info=e)
    finally:
        await bot.close()


def bot_token() -> str:
    """
    Retrieves and validates the required DISCORD_BOT_TOKEN from the environment.
    Also checks for OPENAI_API_KEY, logging a warning if not set.
    Exits the program if the Discord token is missing.

    Returns:
        The valid Discord bot token.
    """
    from environ import DISCORD_BOT_TOKEN, OPENAI_API_KEY

    if not DISCORD_BOT_TOKEN:
        logger.critical("[main.py] 🚫 DISCORD_BOT_TOKEN is not set. Exiting.")
        raise SystemExit(1)

    # Warn if AI features may fail
    if not OPENAI_API_KEY:
        logger.warning("[main.py] ⚠️ OPENAI_API_KEY is not set. AI features may fail.")

    return DISCORD_BOT_TOKEN


def main() -> None:
    """
    Creates the main event loop, sets up signal handlers for clean shutdown,
    and runs the bot until stopped.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop)))

    try:
        loop.run_until_complete(start())
    except (KeyboardInterrupt, SystemExit):
        logger.info("[main.py] 🛑 Shutdown requested by user.")
    finally:
        loop.close()


async def shutdown(loop: asyncio.AbstractEventLoop) -> None:
    """
    Cancels all running tasks, closes the bot, and stops the event loop.
    """
    logger.info("[main.py] 🔌 Cleaning up... Shutting down bot.")
    await bot.close()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


if __name__ == "__main__":
    main()
