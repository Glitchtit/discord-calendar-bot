"""
bot.py: Discord bot setup and initialization, including command sync and error handling.
"""

import sys
import asyncio
from typing import Any, List

import discord
from discord.ext import commands

from log import logger
from environ import DEBUG, COMMAND_PREFIX

# ╔════════════════════════════════════════════════════════════════════╗
# 🤖 Intents & Bot Setup
# ╚════════════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)


# ╔════════════════════════════════════════════════════════════════════╗
# ⚙️ on_ready: Sync Commands & Log Bot Info
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready() -> None:
    """
    Event fired when the bot is connected and ready.
    Attempts to sync slash commands and logs success or failure.
    """
    try:
        synced_commands: List[Any] = await bot.tree.sync()
        logger.info(f"[bot.py] ✅ Bot is ready: {bot.user}")
        logger.info(f"[bot.py] 🌐 Synced {len(synced_commands)} slash commands.")
    except Exception as e:
        logger.exception("[bot.py] Failed to sync slash commands", exc_info=e)


# ╔════════════════════════════════════════════════════════════════════╗
# 🚫 Error Handling for Commands
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_command_error(ctx: commands.Context, error: Exception) -> None:
    """
    A generic event handler for command errors.
    Logs the error and sends a brief message back to the user.
    """
    if hasattr(ctx, 'command') and ctx.command is not None:
        logger.warning(f"[bot.py] Error in command '{ctx.command}': {error}")
    else:
        logger.warning(f"[bot.py] Unhandled error: {error}")

    # Optionally, you can send a user-friendly message:
    try:
        await ctx.send("Oops! Something went wrong. Please try again or contact support.")
    except Exception as e:
        # If we can't even send the error message, log it.
        logger.error(f"[bot.py] Failed to inform user about error: {e}")


# ╔════════════════════════════════════════════════════════════════════╗
# 📦 Load All Cogs Dynamically
# ╚════════════════════════════════════════════════════════════════════╝
async def load_cogs() -> None:
    """
    Loads the 'commands' extension (and potentially other cogs if needed).
    Logs success or failure for debugging.
    """
    try:
        await bot.load_extension("commands")
        logger.info("[bot.py] ✅ Loaded commands extension.")
    except Exception as e:
        logger.exception("[bot.py] Failed to load commands extension.", exc_info=e)


# ╔════════════════════════════════════════════════════════════════════╗
# 🚀 run_bot: Main Entrypoint for Launching the Bot
# ╚════════════════════════════════════════════════════════════════════╝
async def run_bot(discord_token: str) -> None:
    """
    Runs the bot using the provided Discord bot token. Loads cogs,
    starts the bot, and handles graceful shutdown or unexpected crashes.

    Args:
        discord_token: The token used for authentication with Discord.
    """
    await load_cogs()

    try:
        await bot.start(discord_token)
    except KeyboardInterrupt:
        logger.info("[bot.py] 🛑 Bot shutdown requested by user.")
        await bot.close()
    except Exception as e:
        logger.exception("[bot.py] 🚨 Bot crashed unexpectedly", exc_info=e)
        sys.exit(1)
