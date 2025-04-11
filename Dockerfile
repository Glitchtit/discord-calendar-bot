# Use an official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create app directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create directories for persistent data with proper permissions
RUN mkdir -p /data/logs /data/art /data/servers \
    && chmod -R 777 /data \
    && touch /data/.initialized

# Default entrypoint
CMD ["python", "main.py"]
