import os

DEBUG = os.getenv("DEBUG", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("service_account.json")
CALENDAR_SOURCES = os.getenv("CALENDAR_SOURCES")
