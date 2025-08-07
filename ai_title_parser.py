import re
import json
import os
from typing import Dict, Optional
from functools import lru_cache

# ✅ new import style for the modern SDK
try:
    from openai import OpenAI
except ImportError:
    # old SDK fallback
    import openai
    OpenAI = None

from log import logger


class AITitleParser:
    """OpenAI-powered title parser that intelligently simplifies calendar event titles."""

    def __init__(self, model: str = "gpt-5-nano"):
        self.client = None
        self.model = model
        self._setup_openai()

        # Cache for repeated titles to save API calls
        self._title_cache = {}

        # (unchanged) fallback patterns...
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

            if OpenAI is not None:
                # new SDK style
                self.client = OpenAI(api_key=api_key)
            else:
                # old SDK fallback
                openai.api_key = api_key
                self.client = openai

            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}. Using fallback parsing.")
            self.client = None

    def simplify_title(self, original_title: str) -> str:
        if not original_title or not original_title.strip():
            return "Event"

        title = original_title.strip()

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

    def _extract_emojis(self, text: str) -> list:
        # unchanged
        import unicodedata
        emojis = []
        for char in text:
            if unicodedata.category(char) in ['So', 'Sm'] or ord(char) >= 0x1F600:
                emojis.append(char)
        return emojis

    def _simplify_with_openai(self, title: str) -> str:
        """Use OpenAI (Responses API preferred) to intelligently simplify the title."""
        system_prompt = """You are an expert at simplifying calendar event titles, with special expertise in Swedish and Finnish languages including slang and colloquial expressions. Your task is to convert long, complex event titles into concise, clear English titles that capture the essence of the event.

CRITICAL RULES:
1. ALWAYS output in English, regardless of input language
2. Use exactly 5 words when possible (minimum 3, maximum 5)
3. Prefer 5-word titles for better context and clarity
4. Use title case (First Letter Capitalized)
5. Focus on the most important information
6. Remove unnecessary details like times, locations, specific room numbers, recurring indicators
7. Preserve the core meaning and purpose
8. If the original title contains emojis, preserve them in the simplified title
9. Translate Swedish, Finnish, and other languages to English while maintaining meaning
10. Understand Nordic slang and colloquial expressions
11. For work events, prefer generic terms over specific company jargon

Return ONLY the simplified English title, nothing else."""
        # Try twice: slightly higher creativity then ultra-low
        for attempt in range(2):
            try:
                # Prefer the new Responses API
                if hasattr(self.client, "responses"):
                    resp = self.client.responses.create(
                        model=self.model,  # <- gpt-5-nano
                        input=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Simplify this calendar event title to English (may contain Swedish/Finnish slang): {title}"}
                        ],
                        max_output_tokens=60,
                        temperature=0.2 if attempt == 0 else 0.05,
                        top_p=0.8,
                        frequency_penalty=0.1,
                        presence_penalty=0.1,
                    )
                    simplified = (getattr(resp, "output_text", None) or "").strip()
                    if not simplified:
                        # robust extraction if output_text is missing
                        if getattr(resp, "output", None):
                            chunks = []
                            for item in resp.output:
                                if getattr(item, "type", "") == "message":
                                    for c in getattr(item, "content", []):
                                        if getattr(c, "type", "") == "output_text":
                                            chunks.append(getattr(c, "text", ""))
                            simplified = " ".join(chunks).strip()
                else:
                    # Old Chat Completions fallback (older SDKs)
                    resp = self.client.ChatCompletion.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Simplify this calendar event title to English (may contain Swedish/Finnish slang): {title}"}
                        ],
                        max_tokens=60,
                        temperature=0.2 if attempt == 0 else 0.05,
                        top_p=0.8,
                        frequency_penalty=0.1,
                        presence_penalty=0.1,
                    )
                    simplified = resp["choices"][0]["message"]["content"].strip()

                if self._validate_simplified_title(simplified, title):
                    return self._clean_title(simplified)

                logger.debug(f"Attempt {attempt + 1} failed validation: '{simplified}', retrying...")
            except Exception as e:
                logger.debug(f"OpenAI attempt {attempt+1} error: {e}")

        logger.warning(f"OpenAI failed validation after 2 attempts for '{title}', using fallback")
        return self._fallback_simplify(title)

    def _validate_simplified_title(self, simplified: str, original: str) -> bool:
        if not simplified:
            return False

        cleaned = self._clean_title(simplified)
        # remove emojis for word count
        text_words = []
        for word in cleaned.split():
            no_emoji = ''.join(ch for ch in word if not (0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF))
            if no_emoji.strip():
                text_words.append(no_emoji.strip())

        if not (3 <= len(text_words) <= 5):
            return False

        if not self._is_mostly_english(cleaned):
            return False

        meaningless = {'event', 'title', 'calendar', 'appointment', 'meeting only'}
        if cleaned.lower().strip() in meaningless:
            return False

        return True

    def _is_mostly_english(self, text: str) -> bool:
        clean_text = ''.join(ch for ch in text if ch.isalpha() or ch.isspace()).strip()
        if not clean_text:
            return True
        non_english_chars = set('àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ'
                                'ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞŸ'
                                'ßščřžýáíéóúůňñü')
        total_alpha = sum(1 for c in clean_text if c.isalpha())
        non_eng = sum(1 for c in clean_text if c in non_english_chars)
        return not (total_alpha > 0 and (non_eng / total_alpha) > 0.3)

    def _clean_title(self, title: str) -> str:
        cleaned = title.strip('"\'`[]{}()')
        for prefix in ('simplified:', 'title:', 'english:', 'result:'):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()

        # Normalize whitespace and spacing near emojis (best-effort)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    # --- fallbacks unchanged below ---

    def _fallback_simplify(self, title: str) -> str:
        try:
            emojis = self._extract_emojis(title)
            event_type = self._detect_event_type_fallback(title)
            key_terms = self._extract_key_terms_fallback(title)

            words = []
            if emojis:
                words.append(''.join(emojis[:1]))
            if event_type and event_type not in ['event', 'work']:
                words.append(event_type.replace('_', ' ').title())
            for term in key_terms:
                if len(words) >= 5:
                    break
                if term.lower() != event_type and len(term) > 1:
                    words.append(term.title())
            if len(words) < 3:
                additional = self._extract_fallback_words(title)
                for w in additional:
                    if len(words) >= 5:
                        break
                    if w.lower() not in [x.lower().replace('_', ' ') for x in words]:
                        words.append(w.title())

            return self._clean_title(" ".join(words[:5]) or "Event")
        except Exception as e:
            logger.warning(f"Enhanced fallback simplification failed for '{title}': {e}")
            return self._basic_fallback(title)

    def _basic_fallback(self, title: str) -> str:
        try:
            emojis = self._extract_emojis(title)
            words = [w.strip(".,!?()[]{}") for w in title.split()[:5] if w.strip() and len(w) > 1]
            return " ".join(([''.join(emojis[:1])] + words[:4]) if emojis else words) or "Event"
        except:
            return "Event"

    def _detect_event_type_fallback(self, title: str) -> Optional[str]:
        title_lower = title.lower()
        for event_type, pattern in self.fallback_patterns.items():
            if re.search(pattern, title_lower, re.IGNORECASE):
                return event_type
        return None

    def _extract_key_terms_fallback(self, title: str) -> list:
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
            if w[0].isupper(): score += 5
            if any(0x1F300 <= ord(c) <= 0x1FAFF or 0x2600 <= ord(c) <= 0x27BF for c in w): score += 10
            if w.lower() in nordic_bonus_terms: score += 8
            if w[0].isupper() and len(w) > 3 and w.lower() not in noise_words: score += 3
            scored.append((w, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [w for w, _ in scored[:5]]

    def _extract_fallback_words(self, title: str) -> list:
        caps_words = re.findall(r'\b[A-Z][a-z]+\b', title)
        if caps_words:
            return caps_words[:3]
        return [w for w in title.split() if len(w) > 2][:3]

    def clear_cache(self):
        self._title_cache.clear()
        logger.debug("Title cache cleared")


# Global instance
ai_parser = AITitleParser()

def simplify_event_title(title: str) -> str:
    return ai_parser.simplify_title(title)

def clear_title_cache():
    ai_parser.clear_cache()
