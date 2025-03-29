import os

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/service_account.json")
CALENDAR_SOURCES = os.getenv("CALENDAR_SOURCES")
USER_TAG_MAPPING = os.getenv("USER_TAG_MAPPING", "")

