import asyncio
import signal
from log import logger
from tasks import start_background_tasks
from bot import bot

# ╔════════════════════════════════════════════════════════════════════╗
# 🚀 Main Bot Starter (Async)
# ╚════════════════════════════════════════════════════════════════════╝
async def start():
    logger.info("🎬 Starting calendar bot...")

    # Start scheduled tasks (daily/weekly posts, snapshots, etc.)
    start_background_tasks(bot)

    try:
        await bot.start(bot_token())
    except Exception as e:
        logger.exception("❌ Bot crashed during startup or runtime.")
    finally:
        await bot.close()

# ╔════════════════════════════════════════════════════════════════════╗
# 🔐 Token loader (from environ)
# ╚════════════════════════════════════════════════════════════════════╝
def bot_token():
    from environ import DISCORD_BOT_TOKEN
    if not DISCORD_BOT_TOKEN:
        logger.critical("🚫 DISCORD_BOT_TOKEN is not set.")
        raise SystemExit(1)
    return DISCORD_BOT_TOKEN

# ╔════════════════════════════════════════════════════════════════════╗
# 🔁 Entrypoint & Shutdown Hook
# ╚════════════════════════════════════════════════════════════════════╝
def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(loop)))

    try:
        loop.run_until_complete(start())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 Shutdown requested by user.")
    finally:
        loop.close()

# ╔════════════════════════════════════════════════════════════════════╗
# 🧼 Cleanup logic for SIGINT/SIGTERM
# ╚════════════════════════════════════════════════════════════════════╝
async def shutdown(loop):
    logger.info("🔌 Cleaning up... Shutting down bot.")
    await bot.close()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()

# ╔════════════════════════════════════════════════════════════════════╗
# ▶ Run the bot
# ╚════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    main()
