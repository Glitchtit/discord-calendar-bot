FROM python:3.10

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV GOOGLE_APPLICATION_CREDENTIALS="/app/service_account.json"
ENV DISCORD_WEBHOOK_URL=""
ENV CALENDAR_ID=""

# Set entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
