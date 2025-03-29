import os
import time
import random
import requests
from datetime import datetime
from openai import OpenAI
import json

# Load environment variables
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

def generate_greeting(event_titles: list[str]) -> tuple[str | None, str]:
    try:
        today = datetime.now().strftime("%A, %B %d")
        event_summary = ", ".join(event_titles) if event_titles else "no notable engagements"

        style = random.choice(["butler", "bard", "alchemist", "decree"])

        persona_names = {
            "butler": "Sir Reginald the Butler",
            "bard": "Lyricus the Bard",
            "alchemist": "Elarion the Alchemist",
            "decree": "Herald of the Crown"
        }
        persona = persona_names[style]

        base_instruction = (
            "All responses must be written in archaic, Shakespearean English befitting the medieval age. "
            "Use 'thou', 'dost', 'hath', and other appropriate forms. Do not use any modern phrasing."
        )

        if style == "butler":
            prompt = (
                f"Good morrow, my liege. 'Tis {today}, and the courtly matters doth include: {event_summary}.\n"
                f"Compose a morning address in the voice of a loyal medieval butler, under 80 words."
            )
            system_msg = (
                "Thou art a deeply loyal medieval butler who speaketh in reverent, formal Elizabethan English. "
                + base_instruction
            )

        elif style == "bard":
            prompt = (
                f"Hark, noble kin! This fine morn of {today} bringeth tidings of: {event_summary}.\n"
                f"Craft a poetic morning verse as a merry bard would, within 80 words."
            )
            system_msg = (
                "Thou art a poetic bard, who doth speak in rhymes and jests and singsongs of yore. "
                + base_instruction
            )

        elif style == "alchemist":
            prompt = (
                f"Verily, on {today}, the ether shall swirl with: {event_summary}.\n"
                f"Speaketh a morning prophecy in the tongue of a raving alchemist, fewer than 80 words."
            )
            system_msg = (
                "Thou art an eccentric and prophetic alchemist, rambling in visions and olde-tongue riddles. "
                + base_instruction
            )

        elif style == "decree":
            prompt = (
                f"Hearken ye! Upon this {today}, the realm shall see: {event_summary}.\n"
                f"Pronounce a royal decree in bold tone, beneath 80 words."
            )
            system_msg = (
                "Thou art the herald of the crown, proclaiming stately decrees in archaic, noble tongue. "
                + base_instruction
            )

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
        return message, persona
    except Exception as e:
        print(f"[ERROR] Failed to generate greeting: {e}")
        return None, "Unknown Persona"

def generate_image(greeting: str, persona: str, max_retries: int = 3) -> str | None:
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

    for attempt in range(max_retries):
        try:
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

            return image_path

        except Exception as e:
            if hasattr(e, "status_code") and e.status_code == 400 and "content_policy_violation" in str(e).lower():
                print(f"[WARNING] Content policy violation on attempt {attempt + 1}")
                if attempt + 1 < max_retries:
                    time.sleep(1)
                    continue
                else:
                    print("[ERROR] Image prompt blocked after multiple attempts. Skipping image.")
                    return None
            else:
                print(f"[ERROR] Unexpected error on image generation: {e}")
                if attempt + 1 == max_retries:
                    print("[ERROR] Max retries hit. Skipping image.")
                    return None

    return None


def post_greeting_to_discord(events: list[dict] = []):
    if not DISCORD_WEBHOOK_URL:
        print("[DEBUG] No DISCORD_WEBHOOK_URL set.")
        return

    event_titles = [e.get("summary", "a most curious happening") for e in events]
    greeting, persona = generate_greeting(event_titles)
    if not greeting:
        print("[ERROR] Skipping post due to greeting generation failure.")
        return

    image_path = generate_image(greeting, persona)

    print("[DEBUG] Greeting:", greeting)
    print("[DEBUG] Image Path:", image_path)

    if len(greeting) > 4000:
        print("[ERROR] Greeting is too long.")
        return

    embed = {
        "title": f"The Morning Proclamation 📜 — {persona}",
        "description": greeting,
        "color": 0xffe4b5
    }
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            files = {"file": ("generated_image.png", img_file, "image/png")}
            embed["image"] = {"url": "attachment://generated_image.png"}
            payload = {"embeds": [embed]}
            resp = requests.post(DISCORD_WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files=files)
    else:
        payload = {"embeds": [embed]}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)

    if resp.status_code not in [200, 204]:
        print(f"[DEBUG] Discord embed post failed: {resp.status_code} {resp.text}")
    else:
        print("[DEBUG] Discord embed post successful.")

if __name__ == "__main__":
    post_greeting_to_discord()