import discord
from discord.ext import commands
import asyncio
import sys

from log import logger
from environ import DISCORD_BOT_TOKEN, DEBUG, COMMAND_PREFIX

# ╔════════════════════════════════════════════════════════════════════╗
# 🤖 Intents & Bot Setup
# ╚════════════════════════════════════════════════════════════════════╝
intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# ╔════════════════════════════════════════════════════════════════════╗
# ⚙️ On Ready Event — Sync Commands & Log Info
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        logger.info(f"✅ Bot is ready: {bot.user}")
        logger.info(f"🌐 Synced {len(synced)} slash commands.")
    except Exception as e:
        logger.exception("Failed to sync slash commands")

# ╔════════════════════════════════════════════════════════════════════╗
# 🚫 Error Handling
# ╚════════════════════════════════════════════════════════════════════╝
@bot.event
async def on_command_error(ctx, error):
    if hasattr(ctx, 'command') and ctx.command:
        logger.warning(f"Error in command '{ctx.command}': {error}")
    else:
        logger.warning(f"Unhandled error: {error}")

# ╔════════════════════════════════════════════════════════════════════╗
# 📦 Load All Cogs Dynamically
# ╚════════════════════════════════════════════════════════════════════╝
async def load_cogs():
    try:
        await bot.load_extension("commands")
        logger.info("✅ Loaded commands extension.")
    except Exception as e:
        logger.exception("Failed to load commands extension.")

# ╔════════════════════════════════════════════════════════════════════╗
# 🚀 Main Entrypoint
# ╚════════════════════════════════════════════════════════════════════╝
async def run_bot():
    await load_cogs()
    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except KeyboardInterrupt:
        logger.info("🛑 Bot shutdown requested.")
        await bot.close()
    except Exception:
        logger.exception("🚨 Bot crashed unexpectedly")
        sys.exit(1)

# ╔════════════════════════════════════════════════════════════════════╗
# 🔁 Entry
# ╚════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    asyncio.run(run_bot())
