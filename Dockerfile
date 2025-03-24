# Use an official Python base image
FROM python:3.10

# Create a working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
COPY events.json /app/events.json
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source files into /app
COPY . /app/

# Set environment variables
ENV GOOGLE_APPLICATION_CREDENTIALS="/app/service_account.json"
ENV DISCORD_WEBHOOK_URL=""
ENV CALENDAR_ID=""

# Default command
CMD ["python3", "-u", "bot.py"]
