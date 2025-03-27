# Use a lightweight base image with Python 3.10 (you can also use python:3.9-slim, etc.)
FROM python:3.10-slim

# System-wide settings to avoid Python buffering and writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies if needed (for example, git, build tools, etc.)
# If not needed, you can omit the following lines
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy in your requirements
COPY requirements.txt /app/requirements.txt

# Install Python dependencies
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code into the container
COPY . /app

# Optionally set environment variables for your bot and calendar
# (or you can pass them in at runtime via `docker run -e ...`)
# ENV DISCORD_BOT_TOKEN="YourDiscordBotToken"
# ENV ANNOUNCEMENT_CHANNEL_ID="YourChannelID"
# ENV OPENAI_API_KEY="YourOpenAIKey"
# ENV GOOGLE_APPLICATION_CREDENTIALS="/app/service_account.json"
# ENV CALENDAR_SOURCES="google:someone@example.com:T,ics:https://example.com/feed.ics:B"

# Expose no specific port since Discord bots typically don't listen on HTTP ports
# EXPOSE 8080  # For example, only if you had a web server

# Finally, set the default command to run your main script
CMD ["python", "main.py"]
