# Use an official Python base image
FROM python:3.10

# Create a working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source files into /app
COPY . /app/

# Set environment variables (can be overridden at runtime)
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/service_account.json"
ENV DISCORD_WEBHOOK_URL=""
ENV CALENDAR_SOURCES=""
ENV EVENTS_FILE="/data/events.json"

# Ensure /data exists for volume mounting
VOLUME ["/data"]

# Default command
CMD ["python3", "-u", "bot.py"]
