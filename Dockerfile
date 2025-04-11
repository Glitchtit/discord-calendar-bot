# Use a more secure Alpine-based Python image
FROM python:3.11-alpine

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies required for building Python packages
RUN apk add --no-cache gcc musl-dev python3-dev libffi-dev openssl-dev jpeg-dev zlib-dev freetype-dev

# Create app directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create directories for persistent data with proper permissions
RUN mkdir -p /data/logs /data/art /data/servers \
    && chmod -R 777 /data \
    && touch /data/.initialized

# Default entrypoint
CMD ["python", "main.py"]
