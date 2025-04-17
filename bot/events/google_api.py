"""
google_api.py: Google Calendar API setup and service initialization.
"""
import os
import pathlib
from google.oauth2 import service_account
from googleapiclient.discovery import build
from utils.environ import GOOGLE_APPLICATION_CREDENTIALS
from utils.logging import logger

SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Google API credentials and service
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    if not credentials:
        logger.error("No Google Credentials were loaded. Please check your config.")
        service = None
    else:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        logger.info("Google Calendar service initialized.")
except Exception as e:
    logger.exception(f"Error initializing Google Calendar service: {e}")
    logger.debug("Debug: Verify GOOGLE_APPLICATION_CREDENTIALS is set correctly or the file exists.")
    service = None

def get_service_account_email():
    try:
        if not credentials:
            logger.error("No Google credentials available to extract service account email")
            return ""
        return credentials.service_account_email
    except Exception as e:
        logger.exception(f"Error retrieving service account email: {e}")
        return ""
