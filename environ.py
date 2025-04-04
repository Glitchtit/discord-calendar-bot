import os

# ╔════════════════════════════════════════════════════════════════════╗
# ║ ⚙️ Environment Configuration Loader                               ║
# ║ Centralized access to all critical environment variables          ║
# ╚════════════════════════════════════════════════════════════════════╝

# Debug mode toggle — enables verbose logging if set to "true"
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Discord bot token — required for authentication with Discord API
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# Channel ID where announcements and embeds will be posted
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "0"))

# OpenAI API key — required for generating greetings and images
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Path to service account JSON for Google Calendar API
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/app/service_account.json")

# Comma-separated list of calendar sources (e.g., google:id:TAG or ics:url:TAG)
CALENDAR_SOURCES = os.getenv("CALENDAR_SOURCES")

# Comma-separated user-to-tag mappings (e.g., 123456789:T, 987654321:A)
USER_TAG_MAPPING = os.getenv("USER_TAG_MAPPING", "")

# Environment variable for image size
IMAGE_SIZE = "1024x1024"  # or "512x512", "256x256", based on your needs
