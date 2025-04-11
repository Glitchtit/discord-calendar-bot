"""
ai_helpers.py: AI utilities for generating greeting text and images via OpenAI.
Includes improved error handling, retry logic, and type hints.
"""

import random
import requests
import json
import os
import pathlib
import math
import time
from datetime import datetime, timedelta
import logging
import threading
from openai import OpenAI, APIError, RateLimitError, APITimeoutError, APIConnectionError
from utils.environ import OPENAI_API_KEY

# Configure logger
logger = logging.getLogger("calendarbot")

# Global circuit breaker state
_circuit_open = False
_last_error_time = None
_error_count = 0
_reset_after = timedelta(minutes=5)
_error_threshold = 3

# Circuit recovery timer
_recovery_timer = None
_recovery_lock = threading.Lock()

# Initialize OpenAI client with API key from environment
# Use safer initialization with error handling
try:
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=30.0)  # Add explicit timeout
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set. AI-based features will be unavailable.")
except Exception as e:
    logger.exception(f"Error initializing OpenAI client: {e}")
    client = None


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔌 check_api_availability                                          ║
# ║ Implements circuit breaker pattern to prevent API hammering       ║
# ╚════════════════════════════════════════════════════════════════════╝
def check_api_availability():
    global _circuit_open, _last_error_time, _error_count
    
    # If circuit is open, check if enough time has passed to try again
    if _circuit_open:
        if _last_error_time and datetime.now() - _last_error_time > _reset_after:
            logger.info("Circuit breaker reset - attempting to reconnect to OpenAI API")
            _circuit_open = False
            _error_count = 0
            return True
        return False
    return True


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔄 setup_recovery_timer                                            ║
# ║ Schedules API availability check after the circuit breaker opens  ║
# ╚════════════════════════════════════════════════════════════════════╝
def setup_recovery_timer():
    """Schedule a recovery check after the circuit breaker timeout period."""
    global _recovery_timer
    
    with _recovery_lock:
        # Cancel any existing timer
        if _recovery_timer:
            _recovery_timer.cancel()
        
        # Create a new timer to check API availability
        _recovery_timer = threading.Timer(
            _reset_after.total_seconds(),
            _check_api_health
        )
        _recovery_timer.daemon = True  # Don't block app exit
        _recovery_timer.start()
        
        logger.debug(f"Recovery timer scheduled in {_reset_after.total_seconds()} seconds")


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🔎 _check_api_health                                               ║
# ║ Tests the OpenAI API with a minimal request to see if it's back   ║
# ╚════════════════════════════════════════════════════════════════════╝
def _check_api_health():
    """Make a minimal API call to test if OpenAI API is back online."""
    global _circuit_open, _error_count
    
    if not _circuit_open:
        return  # Nothing to do if circuit is already closed
        
    if not client:
        logger.warning("Cannot check API health: OpenAI client not initialized")
        return
    
    try:
        logger.info("Testing OpenAI API availability...")
        # Use a minimal models list request to check API health
        response = client.models.list(limit=1)
        
        # If we get here, API is working
        with _recovery_lock:
            _circuit_open = False
            _error_count = 0
            logger.info("OpenAI API is available again. Circuit closed.")
            
    except Exception as e:
        logger.warning(f"OpenAI API still unavailable: {e}")
        # Schedule another check
        setup_recovery_timer()


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🧯 handle_api_error                                                ║
# ║ Centralized error handling for OpenAI API errors                  ║
# ╚════════════════════════════════════════════════════════════════════╝
def handle_api_error(error, context="API call"):
    global _circuit_open, _last_error_time, _error_count
    
    _error_count += 1
    _last_error_time = datetime.now()
    
    # Open the circuit if we've hit the threshold
    if (_error_count >= _error_threshold) and not _circuit_open:
        _circuit_open = True
        logger.error(f"Circuit breaker opened after {_error_count} errors. Will retry after {_reset_after}")
        # Schedule recovery check
        setup_recovery_timer()
    
    # Handle specific error types
    if isinstance(error, RateLimitError):
        logger.warning(f"OpenAI API rate limit reached during {context}: {error}")
        return "rate_limit"
    elif isinstance(error, APITimeoutError):
        logger.warning(f"OpenAI API timeout during {context}: {error}")
        return "timeout"
    elif isinstance(error, APIConnectionError):
        logger.warning(f"OpenAI API connection error during {context}: {error}")
        return "connection"
    elif isinstance(error, APIError):
        logger.warning(f"OpenAI API error during {context}: {error}")
        return "api_error"
    else:
        logger.exception(f"Unexpected error during {context}: {error}")
        return "unknown"


# ╔════════════════════════════════════════════════════════════════════╗
# 🧠 Generate AI Greeting Text
# ╚════════════════════════════════════════════════════════════════════╝
def generate_greeting(event_titles: list[str], user_names: list[str] = [], max_retries: int = 3) -> tuple[str | None, str]:
    # Check if API is available (circuit breaker pattern)
    if not check_api_availability() or not client:
        logger.warning("OpenAI API unavailable or client not initialized. Using fallback greeting.")
        return generate_fallback_greeting(event_titles), "Fallback Herald"
    
    try:
        today = datetime.now().strftime("%A, %B %d")
        event_summary = ", ".join(event_titles) if event_titles else "no notable engagements"
        logger.debug(f"Generating greeting for events: {event_summary}")

        # Randomly choose one of the medieval personas
        style = random.choice(["butler", "bard", "alchemist", "decree"])
        logger.debug(f"Selected persona style: {style}")

        # Persona name mapping
        persona_names = {
            "butler": "Sir Reginald the Butler",
            "bard": "Lyricus the Bard",
            "alchemist": "Elarion the Alchemist",
            "decree": "Herald of the Crown"
        }
        persona = persona_names[style]

        # Common instruction for medieval tone
        base_instruction = (
            "All responses must be written in archaic, Shakespearean English befitting the medieval age. "
            "Use 'thou', 'dost', 'hath', and other appropriate forms. Do not use any modern phrasing."
        )

        names_clause = ""
        if user_names:
            present_names = ", ".join(user_names)
            names_clause = f"\nThese nobles are present today: {present_names}."

        # Persona-specific prompts and styles
        prompts = {
            "butler": (
                f"Good morrow, my liege. 'Tis {today}, and the courtly matters doth include: {event_summary}.{names_clause}\n"
                f"Compose a morning address in the voice of a loyal medieval butler, under 80 words.",
                "Thou art a deeply loyal medieval butler who speaketh in reverent, formal Elizabethan English."
            ),
            "bard": (
                f"Hark, noble kin! This fine morn of {today} bringeth tidings of: {event_summary}.{names_clause}\n"
                f"Craft a poetic morning verse as a merry bard would, within 80 words.",
                "Thou art a poetic bard, who doth speak in rhymes and jests and singsongs of yore."
            ),
            "alchemist": (
                f"Verily, on {today}, the ether shall swirl with: {event_summary}.{names_clause}\n"
                f"Speaketh a morning prophecy in the tongue of a raving alchemist, fewer than 80 words.",
                "Thou art an eccentric and prophetic alchemist, rambling in visions and olde-tongue riddles."
            ),
            "decree": (
                f"Hearken ye! Upon this {today}, the realm shall see: {event_summary}.{names_clause}\n"
                f"Pronounce a royal decree in bold tone, beneath 80 words.",
                "Thou art the herald of the crown, proclaiming stately decrees in archaic, noble tongue."
            )
        }

        prompt, persona_instruction = prompts[style]
        system_msg = persona_instruction + " " + base_instruction

        # Implement retry with exponential backoff
        for attempt in range(max_retries):
            try:
                # OpenAI API call for generating the greeting
                logger.debug(f"Calling OpenAI API for greeting (attempt {attempt+1}/{max_retries})...")
                
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=150,
                )

                message = response.choices[0].message.content.strip()
                message += f"\n\n— {persona}"
                logger.info(f"Greeting generated by {persona}")
                return message, persona
                
            except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
                error_type = handle_api_error(e, f"greeting generation (attempt {attempt+1})")
                
                # If we're on the last attempt, use fallback
                if attempt == max_retries - 1:
                    logger.warning(f"All retries failed for generate_greeting. Using fallback.")
                    return generate_fallback_greeting(event_titles), f"Fallback {persona}"
                
                # Calculate backoff time (exponential with jitter)
                backoff = (2 ** attempt) + random.uniform(0, 1)
                logger.info(f"Retrying in {backoff:.2f} seconds...")
                time.sleep(backoff)
                
    except Exception as e:
        logger.exception(f"Failed to generate greeting: {e}")
        return generate_fallback_greeting(event_titles), "Fallback Herald"
    
    # If we got here, all retries failed
    return generate_fallback_greeting(event_titles), "Fallback Herald"


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 💬 generate_fallback_greeting                                      ║
# ║ Creates a simple greeting when OpenAI API is unavailable          ║
# ╚════════════════════════════════════════════════════════════════════╝
def generate_fallback_greeting(event_titles: list[str]) -> str:
    today = datetime.now().strftime("%A, %B %d")
    
    if not event_titles:
        return f"Hear ye, hear ye! On this day of {today}, the kingdom awaits thy noble deeds. May thy day be filled with merriment and good fortune!\n\n— Royal Messenger"
    
    events_count = len(event_titles)
    event_word = "event" if events_count == 1 else "events"
    
    return f"Oyez, oyez! On this fine {today}, {events_count} {event_word} await thee in thy royal calendar. May thy schedule be favorable and thy meetings most productive!\n\n— Royal Messenger"


# ╔════════════════════════════════════════════════════════════════════╗
# 🎨 Generate Image from Text Prompt
# ╚════════════════════════════════════════════════════════════════════╝
def generate_image(greeting: str, persona: str, max_retries: int = 3) -> str | None:
    # Check if API is available (circuit breaker pattern)
    if not check_api_availability() or not client:
        logger.warning("OpenAI API unavailable or client not initialized. Skipping image generation.")
        return None
        
    # Persona-specific visual styles
    persona_vibe = {
        "Sir Reginald the Butler": "a dignified, well-dressed butler bowing in a candlelit medieval hallway",
        "Lyricus the Bard": "a cheerful bard strumming a lute in a bustling medieval tavern",
        "Elarion the Alchemist": "an eccentric alchemist surrounded by glowing potions in a cluttered tower",
        "Herald of the Crown": "a royal herald on horseback with scrolls, in front of a castle courtyard",
        "Fallback Herald": "a royal messenger with a scroll in a medieval town square",
    }

    visual_context = persona_vibe.get(persona, "medieval character")
    prompt = (
        f"Scene inspired by the following proclamation: '{greeting}'\n"
        f"Depict {visual_context}, illustrated in the style of the Bayeux Tapestry, "
        f"with humorous medieval cartoon characters, textured linen background, and stitched-looking text."
    )

    # Define data directories with platform-agnostic paths
    # Primary data directory
    data_dir = pathlib.Path("/data")
    art_dir = data_dir / "art"
    
    # Fallback directories
    script_dir = pathlib.Path(__file__).parent.parent  # Go up one level from utils/
    fallback_art_dir = script_dir / "data" / "art"
    
    # Another fallback using temp directory
    temp_art_dir = pathlib.Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "art"))

    # Retry loop with exponential backoff
    for attempt in range(max_retries):
        try:
            logger.debug(f"[{persona}] Generating image (attempt {attempt + 1}/{max_retries})...")
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024",  # Hard-code image size instead of using variable
                response_format="url"
            )
            image_url = response.data[0].url
            
            # Download with timeout and retries
            download_attempts = 2
            for dl_attempt in range(download_attempts):
                try:
                    image_response = requests.get(image_url, timeout=20)
                    image_response.raise_for_status()
                    break
                except requests.exceptions.Timeout:
                    if dl_attempt < download_attempts - 1:
                        logger.warning(f"Download timeout, retrying ({dl_attempt+1}/{download_attempts})...")
                        time.sleep(2)
                    else:
                        raise

            # Timestamp for unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"generated_{timestamp}.png"
            
            # Try saving to each potential directory until one works
            for directory in [art_dir, fallback_art_dir, temp_art_dir]:
                try:
                    # Create directory if it doesn't exist
                    directory.mkdir(parents=True, exist_ok=True)
                    
                    # Full path to the file
                    image_path = directory / filename
                    
                    # Save the image
                    with open(image_path, "wb") as f:
                        f.write(image_response.content)
                        
                    logger.info(f"Image saved to {image_path}")
                    return str(image_path)
                except (PermissionError, OSError) as e:
                    logger.warning(f"Could not save to {directory}: {e}")
                    continue  # Try next directory
            
            # If we get here, all directories failed
            logger.error("Failed to save image to any directory. Check permissions.")
            return None

        except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:
            error_type = handle_api_error(e, f"image generation (attempt {attempt+1})")
            
            if attempt == max_retries - 1:
                logger.error("All retries for image generation failed.")
                return None
                
            # Calculate backoff time (exponential with jitter)
            backoff = (2 ** attempt) + random.uniform(0, 1)
            logger.info(f"Retrying image generation in {backoff:.2f} seconds...")
            time.sleep(backoff)
            
        except requests.exceptions.RequestException as e:
            logger.exception(f"Network error during image generation (attempt {attempt + 1}): {e}")
            if attempt + 1 == max_retries:
                logger.error("Max retries reached. Skipping image.")
                return None
                
        except Exception as e:
            logger.exception(f"Unexpected error during image generation (attempt {attempt + 1}): {e}")
            if attempt + 1 == max_retries:
                logger.error("Max retries reached. Skipping image.")
                return None

    return None

