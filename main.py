from bot import bot
from environ import DISCORD_BOT_TOKEN
from log import logger


def main():
    if not DISCORD_BOT_TOKEN:
        raise ValueError("DISCORD_BOT_TOKEN is not set in environment.")
    logger.info("Starting Discord bot...")
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    main()
