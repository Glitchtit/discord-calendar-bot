import os
import json
import hashlib
import requests
from datetime import datetime
from ics import Calendar as ICS_Calendar
from google.oauth2 import service_account
from googleapiclient.discovery import build
from environ import GOOGLE_APPLICATION_CREDENTIALS, CALENDAR_SOURCES, USER_TAG_MAPPING
from log import logger

SERVICE_ACCOUNT_FILE = GOOGLE_APPLICATION_CREDENTIALS
SCOPES = ["https://www.googleapis.com/auth/calendar"]
EVENTS_FILE = "/data/events.json"

logger.debug(f"Loading Google credentials from: {SERVICE_ACCOUNT_FILE}")
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)
service = build("calendar", "v3", credentials=credentials)
logger.info("Google Calendar service initialized.")

# User ID → TAG mapping (from env)
def get_user_tag_mapping():
    mapping = {}
    for entry in USER_TAG_MAPPING.split(","):
        if ":" in entry:
            user_id, tag = entry.strip().split(":", 1)
            try:
                mapping[int(user_id)] = tag.strip().upper()
            except ValueError:
                logger.warning(f"Invalid user ID in USER_TAG_MAPPING: {entry}")
    return mapping

USER_TAG_MAP = get_user_tag_mapping()

# Runtime-mutable tag-to-name and tag-to-color (populated by bot.py)
TAG_NAMES = {}
TAG_COLORS = {}

def get_name_for_tag(tag):
    return TAG_NAMES.get(tag, tag)

def get_color_for_tag(tag):
    return TAG_COLORS.get(tag, 0x95a5a6)  # default grey

def parse_calendar_sources():
    parsed = []
    for entry in CALENDAR_SOURCES.split(","):
        entry = entry.strip()
        if entry.startswith("google:") or entry.startswith("ics:"):
            prefix, rest = entry.split(":", 1)
            if ":" in rest:
                id_or_url, tag = rest.rsplit(":", 1)
                parsed.append((prefix, id_or_url.strip(), tag.strip().upper()))
                logger.debug(f"Parsed calendar source: {prefix}:{id_or_url.strip()} (tag={tag.strip().upper()})")
    return parsed

def fetch_google_calendar_metadata(calendar_id):
    try:
        service.calendarList().insert(body={"id": calendar_id}).execute()
    except Exception as e:
        if "Already Exists" not in str(e):
            logger.warning(f"Couldn't subscribe to {calendar_id}: {e}")
    try:
        cal = service.calendarList().get(calendarId=calendar_id).execute()
        name = cal.get("summaryOverride") or cal.get("summary") or calendar_id
    except Exception as e:
        logger.warning(f"Couldn't get metadata for Google calendar {calendar_id}: {e}")
        name = calendar_id
    logger.debug(f"Loaded Google calendar metadata: {name}")
    return {"type": "google", "id": calendar_id, "name": name}

def fetch_ics_calendar_metadata(url):
    name = url.split("/")[-1].split("?")[0] or "ICS Calendar"
    logger.debug(f"Loaded ICS calendar metadata: {name}")
    return {"type": "ics", "id": url, "name": name}

def load_calendar_sources():
    logger.info("Loading calendar sources...")
    grouped = {}
    for ctype, cid, tag in parse_calendar_sources():
        meta = fetch_google_calendar_metadata(cid) if ctype == "google" else fetch_ics_calendar_metadata(cid)
        meta["tag"] = tag
        grouped.setdefault(tag, []).append(meta)
        logger.debug(f"Calendar loaded: {meta}")
    return grouped

GROUPED_CALENDARS = load_calendar_sources()
