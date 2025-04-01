from bot import bot
from environ import DISCORD_BOT_TOKEN
from log import logger


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🚀 main                                                            ║
# ║ Entry point for launching the Discord bot                         ║
# ║ Ensures environment variable is present before starting the bot   ║
# ╚════════════════════════════════════════════════════════════════════╝
def main():
    if not DISCORD_BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN is not set in environment.")
    logger.info("Starting Discord bot...")
    bot.run(DISCORD_BOT_TOKEN)


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧩 __main__ check                                                  ║
# ║ Allows script to be run directly (e.g., `python main.py`)         ║
# ╚════════════════════════════════════════════════════════════════════╝
if __name__ == "__main__":
    main()
