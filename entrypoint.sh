#!/bin/sh

# Check if events.json exists, create if not
if [ ! -f /app/events.json ]; then
  echo "{}" > /app/events.json
fi

# Execute the original CMD
exec python3 -u bot.py
