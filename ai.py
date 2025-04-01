import time
import random
import requests
import json
import os
from datetime import datetime
from openai import OpenAI
from log import logger

# Initialize OpenAI client with API key from environment
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🗣️ generate_greeting                                               ║
# ║ Creates a medieval-style greeting message in a randomized persona ║
# ║ based on upcoming event titles and present user names.            ║
# ╚════════════════════════════════════════════════════════════════════╝
def generate_greeting(event_titles: list[str], user_names: list[str] = []) -> tuple[str | None, str]:
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

        # OpenAI API call for generating the greeting
        logger.debug("Calling OpenAI API for greeting...")
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
    except Exception:
        logger.exception("Failed to generate greeting")
        return None, "Unknown Persona"


# ╔════════════════════════════════════════════════════════════════════╗
# ║ 🎨 generate_image                                                  ║
# ║ Creates a DALL·E-generated image based on the greeting and        ║
# ║ persona vibe, using a stylized Bayeux Tapestry art prompt.        ║
# ╚════════════════════════════════════════════════════════════════════╝
def generate_image(greeting: str, persona: str, max_retries: int = 3) -> str | None:
    # Persona-specific visual styles
    persona_vibe = {
        "Sir Reginald the Butler": "a dignified, well-dressed butler bowing in a candlelit medieval hallway",
        "Lyricus the Bard": "a cheerful bard strumming a lute in a bustling medieval tavern",
        "Elarion the Alchemist": "an eccentric alchemist surrounded by glowing potions in a cluttered tower",
        "Herald of the Crown": "a royal herald on horseback with scrolls, in front of a castle courtyard"
    }

    visual_context = persona_vibe.get(persona, "medieval character")
    prompt = (
        f"Scene inspired by the following proclamation: '{greeting}'\n"
        f"Depict {visual_context}, illustrated in the style of the Bayeux Tapestry, "
        f"with humorous medieval cartoon characters, textured linen background, and stitched-looking text."
    )

    # Retry loop for content policy or transient failures
    for attempt in range(max_retries):
        try:
            logger.debug(f"[{persona}] Generating image (attempt {attempt + 1})...")
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
                response_format="url"
            )
            image_url = response.data[0].url
            image_response = requests.get(image_url)
            image_response.raise_for_status()

            os.makedirs("/data/art", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            image_path = f"/data/art/generated_{timestamp}.png"
            with open(image_path, "wb") as f:
                f.write(image_response.content)

            logger.info(f"Image saved to {image_path}")
            return image_path

        except Exception as e:
            # Retry if OpenAI blocks due to content policy
            if hasattr(e, "status_code") and e.status_code == 400 and "content_policy_violation" in str(e).lower():
                logger.warning(f"[{persona}] Content policy violation (attempt {attempt + 1})")
                if attempt + 1 < max_retries:
                    time.sleep(1)
                    continue
                else:
                    logger.error("Image prompt blocked after multiple attempts.")
                    return None
            else:
                logger.exception("Unexpected error during image generation")
                if attempt + 1 == max_retries:
                    logger.error("Max retries reached. Skipping image.")
                    return None

    return None
