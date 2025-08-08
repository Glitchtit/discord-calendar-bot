import re
import os
from typing import Optional

# No top-level OpenAI imports; we'll lazy-load in _setup_openai to avoid env issues
OpenAI = None  # type: ignore
openai = None  # type: ignore

from log import logger


class AITitleParser:
    """OpenAI-powered title parser that intelligently simplifies calendar event titles."""

    def __init__(self, model: str = "gpt-5-nano"):
        self.client = None
        self.model = model
        self._setup_openai()
        self._title_cache = {}

        # Enhanced fallback patterns with Nordic languages and slang
        self.fallback_patterns = {
            'meeting': r'\b(meeting|meet|call|conference|sync|standup|retrospective|review|möte|mötesdjur|träff|sammankallelse|kokous|tapaaminen|palaveri|neuvottelu|reunión|réunion|besprechung|vergadering)\b',
            'appointment': r'\b(appointment|appt|visit|consultation|checkup|besök|tid|tidsbokning|aika|varaus|käynti|termin|cita|rendez-vous|afspraak)\b',
            'class': r'\b(class|lecture|lesson|training|workshop|seminar|EM|GT|klass|lektion|föreläsning|utbildning|kurs|kurssit|luento|opetus|koulutus|curso|cours|unterricht|les)\b',
            'event': r'\b(event|party|celebration|ceremony|launch|evenemang|fest|kalas|firande|tillfälle|tapahtuma|juhla|juhlat|bileet|evento|événement|veranstaltung|evenement)\b',
            'deadline': r'\b(deadline|due|submit|delivery|finish|deadline|sista|datum|inlämning|palautus|määräaika|frist|plazo|échéance)\b',
            'interview': r'\b(interview|screening|hiring|intervju|anställningsintervju|jobbintervju|haastattelu|työhaastattelu|entrevista|entretien|vorstellungsgespräch|sollicitatiegesprek)\b',
            'lunch': r'\b(lunch|dinner|breakfast|meal|eat|lunch|middag|frukost|måltid|äta|lounas|ruoka|syödä|aamiainen|päivällinen|almuerzo|déjeuner|mittagessen|ontbijt)\b',
            'travel': r'\b(flight|travel|trip|vacation|holiday|resa|flyg|semester|ledighet|matka|loma|lento|viaje|voyage|reise|reis|vakantie)\b',
            'birthday': r'\b(birthday|bday|anniversary|födelsedag|bursdag|grattis|syntymäpäivä|synttärit|syndet|cumpleaños|anniversaire|geburtstag|verjaardag)\b',
            'reminder': r'\b(reminder|remind|follow.?up|todo|påminnelse|kom.?ihåg|muistutus|muista|recordatorio|rappel|erinnerung|herinnering)\b',
            'work': r'\b(work|job|arbete|jobb|ansvarsarbetstid|distansarbete|hemarbete|työ|etätyö|kotityö|trabajo|travail|arbeit|werk)\b',
            'doctor': r'\b(doctor|medical|health|läkare|doktor|hälsa|vård|lääkäri|terveys|hoito|doctor|médecin|arzt|dokter)\b',
            'shopping': r'\b(shopping|store|buy|handla|köpa|affär|butik|ostokset|kauppa|ostaa|compras|courses|einkaufen|winkelen)\b',
            'coffee': r'\b(coffee|kaffe|fika|kahvi|café|kaffepaus|kahvitauko)\b',
            'gym': r'\b(gym|träning|motion|idrott|kuntoilu|liikunta|urheilu|training)\b',
            'study': r'\b(studera|plugga|läsa|opiskella|lukea|tentti|koe|exam|prov)\b',
            'call': r'\b(ring|ringa|soita|puhelu|samtal|call)\b'
        }

    def _setup_openai(self):
        """Initialize OpenAI client with API key from environment."""
        try:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                logger.warning("OPENAI_API_KEY not found. Falling back to pattern-based parsing.")
                return

            # Try modern SDK first
            global OpenAI, openai
            try:
                from openai import OpenAI as _OpenAI  # type: ignore
                OpenAI = _OpenAI
                self.client = OpenAI(api_key=api_key)
            except Exception:
                # Old SDK fallback
                try:
                    import openai as _openai  # type: ignore
                    openai = _openai
                except Exception as ie:
                    raise RuntimeError("openai SDK not available") from ie
                openai.api_key = api_key
                self.client = openai

            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}. Using fallback parsing.")
            self.client = None

    def simplify_title(self, original_title: str) -> str:
        """
        Simplify an event title to maximum 5 words using OpenAI (gpt-5-nano), with robust fallbacks.
        """
        if not original_title or not original_title.strip():
            return "Event"

        title = original_title.strip()

        # Cache first
        if title in self._title_cache:
            logger.debug(f"Using cached result for: '{title}'")
            return self._title_cache[title]

        try:
            logger.debug(f"Simplifying title: '{title}'")
            if self.client:
                simplified = self._simplify_with_openai(title)
            else:
                simplified = self._fallback_simplify(title)

            self._title_cache[title] = simplified
            logger.debug(f"Simplified '{title}' -> '{simplified}'")
            return simplified
        except Exception as e:
            logger.warning(f"Error simplifying title '{original_title}': {e}")
            return self._fallback_simplify(original_title)

    # -------------------- OpenAI calls --------------------

    def _extract_text_from_response(self, resp) -> str:
        """
        Robustly extract plain text from both Responses API and chat.completions.
        """
        # New Responses API (python SDK >= 1.0)
        text = getattr(resp, "output_text", None)
        if text:
            return text.strip()

        # Fallback: iterate structured output (Responses API)
        out = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", "") == "message":
                for c in getattr(item, "content", []) or []:
                    # Responses API uses content parts with type "text"
                    if getattr(c, "type", "") in ("text", "output_text"):
                        t = getattr(c, "text", "")
                        if t:
                            out.append(t)
        if out:
            return " ".join(out).strip()

        # Chat Completions (typed object)
        try:
            choices = getattr(resp, "choices", None)
            if choices and len(choices) > 0:
                msg = getattr(choices[0], "message", None)
                content = getattr(msg, "content", None)
                if isinstance(content, str):
                    return content.strip()
        except Exception:
            pass

        # Chat Completions (dict-like)
        try:
            return resp["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

        return ""

    def _simplify_with_openai(self, title: str) -> str:
        """Use OpenAI (Responses API preferred) to intelligently simplify the title."""
        system_prompt = (
            "You simplify calendar event titles (incl. Swedish/Finnish slang) into concise English.\n"
            "Rules:\n"
            "1) Output ONLY the simplified English title.\n"
            "2) Prefer exactly 5 words (min 3, max 5).\n"
            "3) Use Title Case.\n"
            "4) Keep emojis from the original if present.\n"
            "5) Remove times/rooms/IDs.\n"
        )

        def _call_openai(temp: float, format_only: bool = False) -> str:
            user_prompt = (
                f"Simplify this title: {title}"
                if not format_only else
                f"Reformat this text into exactly 3–5 Title-Case words (keep emojis, no punctuation): {title}"
            )

            if (self.client is not None) and hasattr(self.client, "responses"):
                # Responses API (modern) — use structured content parts for maximum compatibility
                resp = self.client.responses.create(
                    model=self.model,
                    input=[
                        {
                            "role": "system",
                            "content": [
                                {"type": "input_text", "text": system_prompt},
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": user_prompt},
                            ],
                        },
                    ],
                    max_output_tokens=50,
                )
            else:
                # Chat Completions fallback (prefer modern path if available)
                if (self.client is not None) and hasattr(self.client, "chat") and hasattr(self.client.chat, "completions"):
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=50,
                        temperature=temp,
                        top_p=0.8,
                        frequency_penalty=0.1,
                        presence_penalty=0.1,
                    )
                elif (self.client is not None) and hasattr(self.client, "ChatCompletion"):
                    resp = self.client.ChatCompletion.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        max_tokens=50,
                        temperature=temp,
                        top_p=0.8,
                        frequency_penalty=0.1,
                        presence_penalty=0.1,
                    )
                else:
                    raise RuntimeError("No compatible chat completions API available in OpenAI client")
            return self._extract_text_from_response(resp)

        # Attempt 1: normal simplify (slightly creative)
        try:
            simplified = _call_openai(0.2, format_only=False).strip()
            if self._validate_simplified_title(simplified, title):
                return self._clean_title(simplified)
            else:
                logger.debug(f"Attempt 1 failed validation: '{simplified}'")
        except Exception as e:
            logger.debug(f"OpenAI attempt 1 error: {e}")

        # Attempt 2: deterministic format-only pass
        try:
            simplified = _call_openai(0.0, format_only=True).strip()
            if self._validate_simplified_title(simplified, title):
                return self._clean_title(simplified)
            else:
                logger.debug(f"Attempt 2 failed validation: '{simplified}'")
        except Exception as e:
            logger.debug(f"OpenAI attempt 2 error: {e}")

        logger.warning(f"OpenAI failed validation after 2 attempts for '{title}', using fallback")
        return self._fallback_simplify(title)

    # -------------------- Validation & Cleaning --------------------

    def _extract_emojis(self, text: str) -> list:
        """Extract emojis from text using Unicode ranges."""
        import unicodedata
        emojis = []
        for char in text:
            # treat symbols/emoji as emojis
            if unicodedata.category(char) in ['So', 'Sm'] or 0x1F300 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF:
                emojis.append(char)
        return emojis

    def _validate_simplified_title(self, simplified: str, original: str) -> bool:
        if not simplified:
            return False

        cleaned = self._clean_title(simplified)

        # Split words, ignore emojis
        tokens = cleaned.split()
        text_words = []
        for tok in tokens:
            no_emoji = ''.join(
                ch for ch in tok
                if not (0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF)
            )
            no_emoji = re.sub(r"[^\w\s\-']", "", no_emoji)
            if no_emoji.strip():
                text_words.append(no_emoji.strip())

        # ✅ Relaxed: 2–6 words instead of strict 3–5
        if not (2 <= len(text_words) <= 6):
            return False

        # ✅ Softer English check – allow if at least half the words contain A–Z
        if not self._is_mostly_english(cleaned):
            latin_like = sum(bool(re.search(r"[A-Za-z]", w)) for w in text_words)
            if latin_like / max(1, len(text_words)) < 0.5:
                return False

        meaningless = {'event', 'title', 'calendar', 'appointment', 'meeting only'}
        if cleaned.lower().strip() in meaningless:
            return False

        return True


    def _is_mostly_english(self, text: str) -> bool:
        """Basic check if text is mostly English."""
        clean_text = ''.join(ch for ch in text if ch.isalpha() or ch.isspace()).strip()
        if not clean_text:
            return True  # emojis-only is fine

        non_english_chars = set('àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ'
                                'ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞŸ'
                                'ßščřžýáíéóúůňñü')
        total_alpha = sum(1 for c in clean_text if c.isalpha())
        non_eng = sum(1 for c in clean_text if c in non_english_chars)
        return not (total_alpha > 0 and (non_eng / total_alpha) > 0.3)

    def _clean_title(self, title: str) -> str:
        """Clean and format the title properly."""
        cleaned = title.strip('"\'`[]{}() \t\r\n')
        # Remove common prefixes
        for prefix in ('simplified:', 'title:', 'english:', 'result:'):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        # Normalize whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Title Case while preserving emojis/symbols
        def _tc(word):
            if re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", word):
                return word
            return word.title()

        cleaned = " ".join(_tc(w) for w in cleaned.split())
        return cleaned

    # -------------------- Fallbacks --------------------

    def _fallback_simplify(self, title: str) -> str:
        """Enhanced fallback pattern-based simplification when OpenAI is unavailable."""
        try:
            emojis = self._extract_emojis(title)
            event_type = self._detect_event_type_fallback(title)
            key_terms = self._extract_key_terms_fallback(title)

            words = []
            if emojis:
                words.append(''.join(emojis[:1]))  # keep only one to save space

            if event_type and event_type not in ['event', 'work']:
                if event_type == 'remote work':
                    words.append('Work')
                else:
                    words.append(event_type.replace('_', ' ').title())

            for term in key_terms:
                if len(words) >= 5:
                    break
                if term.lower() != event_type and len(term) > 1:
                    words.append(term.title())

            if len(words) < 3:
                additional = self._extract_fallback_words(title)
                for word in additional:
                    if len(words) >= 5:
                        break
                    if word.lower() not in [w.lower().replace('_', ' ') for w in words]:
                        words.append(word.title())

            result = " ".join(words[:5]) if words else "Event"
            return self._clean_title(result)
        except Exception as e:
            logger.warning(f"Enhanced fallback simplification failed for '{title}': {e}")
            return self._basic_fallback(title)

    def _basic_fallback(self, title: str) -> str:
        """Ultimate basic fallback."""
        try:
            emojis = self._extract_emojis(title)
            words = title.split()[:5]
            clean_words = [word.strip(".,!?()[]{}") for word in words if word.strip() and len(word) > 1]
            if emojis:
                return " ".join([''.join(emojis[:1])] + clean_words[:4]) or "Event"
            return " ".join(clean_words) or "Event"
        except Exception:
            return "Event"

    def _detect_event_type_fallback(self, title: str) -> Optional[str]:
        """Detect event type using fallback patterns."""
        title_lower = title.lower()
        for event_type, pattern in self.fallback_patterns.items():
            if re.search(pattern, title_lower, re.IGNORECASE):
                return event_type
        return None

    def _extract_key_terms_fallback(self, title: str) -> list:
        """Extract key terms using simple pattern matching with Nordic language support."""
        cleaned = re.sub(r'[^\w\s\-åäöÅÄÖ\U0001F300-\U0001FAFF\u2600-\u27BF]', ' ', title)
        words = [w.strip() for w in cleaned.split() if w.strip() and len(w) > 1]

        noise_words = {
            'the', 'and', 'with', 'for', 'meeting', 'call', 'at', 'on', 'in',
            'med', 'och', 'för', 'på', 'i', 'av', 'till', 'från', 'det', 'den', 'är', 'att',
            'ja', 'kanssa', 'että', 'on', 'se', 'tai', 'kun', 'klo', 'kl', 'time', 'tid'
        }
        filtered = [w for w in words if w.lower() not in noise_words]

        nordic_bonus_terms = {
            'fika', 'träff', 'möte', 'plugga', 'treenit', 'bileet', 'synttärit',
            'kokous', 'tapaaminen', 'kahvitauko', 'ruokaostokset', 'lääkäri',
            'hammaslääkäri', 'tandläkare', 'arbetstid', 'etätyö', 'hemarbete'
        }

        scored = []
        for w in filtered:
            score = len(w)
            if w[0].isupper():
                score += 5
            if any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in w):
                score += 10
            if w.lower() in nordic_bonus_terms:
                score += 8
            if w[0].isupper() and len(w) > 3 and w.lower() not in noise_words:
                score += 3
            scored.append((w, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        return [word for word, _ in scored[:5]]

    def _extract_fallback_words(self, title: str) -> list:
        """Extract words as ultimate fallback."""
        caps_words = re.findall(r'\b[A-Z][a-z]+\b', title)
        if caps_words:
            return caps_words[:3]
        return [w for w in title.split() if len(w) > 2][:3]

    def clear_cache(self):
        """Clear the title cache."""
        self._title_cache.clear()
        logger.debug("Title cache cleared")


# Global instance
ai_parser = AITitleParser()

def simplify_event_title(title: str) -> str:
    """Public function to simplify event titles using OpenAI."""
    return ai_parser.simplify_title(title)

def clear_title_cache():
    """Public function to clear the title cache."""
    ai_parser.clear_cache()
