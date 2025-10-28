import re
import json
import openai
from typing import Dict, Optional
from log import logger
import os
from functools import lru_cache

class AITitleParser:
    """OpenAI-powered title parser that intelligently simplifies calendar event titles."""
    
    def __init__(self):
        # Initialize OpenAI client
        self.client = None
        self._setup_openai()
        
        # Cache for repeated titles to save API calls
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
                logger.warning("OPENAI_API_KEY not found in environment variables. Falling back to pattern-based parsing.")
                return
                
            self.client = openai.OpenAI(api_key=api_key)
            logger.info("OpenAI client initialized successfully")
            
        except Exception as e:
            logger.warning(f"Failed to initialize OpenAI client: {e}. Using fallback parsing.")
            self.client = None

    def simplify_title(self, original_title: str) -> str:
        """
        Simplify an event title to maximum 5 words using OpenAI API.
        
        Args:
            original_title: The original event title
            
        Returns:
            Simplified title (max 5 words)
        """
        try:
            if not original_title or not original_title.strip():
                return "Event"
                
            title = original_title.strip()
            
            # Check cache first
            if title in self._title_cache:
                logger.debug(f"Using cached result for: '{title}'")
                return self._title_cache[title]
            
            logger.debug(f"Simplifying title: '{title}'")
            
            # Try OpenAI first, fall back to pattern matching
            if self.client:
                simplified = self._simplify_with_openai(title)
            else:
                simplified = self._fallback_simplify(title)
            
            # Cache the result
            self._title_cache[title] = simplified
            
            logger.debug(f"Simplified '{title}' -> '{simplified}'")
            return simplified
            
        except Exception as e:
            logger.warning(f"Error simplifying title '{original_title}': {e}")
            return self._fallback_simplify(original_title)

    def _extract_emojis(self, text: str) -> list:
        """Extract emojis from text using Unicode ranges."""
        import unicodedata
        emojis = []
        for char in text:
            # Check for emoji using Unicode categories
            if unicodedata.category(char) in ['So', 'Sm'] or ord(char) > 0x1F600:
                emojis.append(char)
        return emojis

    def _simplify_with_openai(self, title: str) -> str:
        """Use OpenAI API to intelligently simplify the title."""
        try:
            system_prompt = """You are an expert at simplifying calendar event titles, with special expertise in Swedish and Finnish languages including slang and colloquial expressions. Your task is to identify the language of the input title and create a concise summary in that SAME language.

CRITICAL RULES:
1. FIRST identify the language: English, Swedish, or Finnish (including slang and dialects)
2. ALWAYS output in the SAME language as the input
3. Use exactly 5 words when possible (minimum 3, maximum 5)
4. Prefer 5-word summaries for better context and clarity
5. Use title case (First Letter Capitalized)
6. Focus on the most important information
7. Remove unnecessary details like times, locations, specific room numbers, recurring indicators
8. Preserve the core meaning and purpose
9. If the original title contains emojis, preserve them in the simplified title
10. Understand Nordic slang and colloquial expressions
11. For work events, prefer generic terms over specific company jargon

SWEDISH LANGUAGE & SLANG EXAMPLES (5 words preferred, OUTPUT IN SWEDISH):
"Möte med utvecklingsteam klockan 10" → "Möte Med Utvecklingsteam"
"Fika med kollegorna på kontoret" → "Fika Med Kollegorna"
"Träff med chefen angående projekt" → "Träff Med Chefen"
"Tandläkartid kl 14 i City" → "Tandläkartid Klockan 14"
"Mamma födelsedag hemma" → "Mamma Födelsedag"
"Plugga inför tentan i matematik" → "Plugga Inför Tentan"
"Handla mat efter jobbet Ica" → "Handla Mat Efter Jobbet"
"Träning på gymmet kl 18" → "Träning På Gymmet"
"Läkarbesök för hälsokontroll" → "Läkarbesök Hälsokontroll"
"Jobbintervju på Microsoft Stockholm" → "Jobbintervju På Microsoft"
"Middag med familjen hemma" → "Middag Med Familjen"
"Ansvarsarbetstid hemma distans" → "Ansvarsarbetstid Hemma"
"Undervisning i matematik kl 13" → "Undervisning I Matematik"
"Ringa mormor på kvällen" → "Ringa Mormor"
"Städa lägenheten helgen" → "Städa Lägenheten"
"Veckomöte projektgrupp Alpha" → "Veckomöte Projektgrupp Alpha"
"Kvartalsmöte försäljning Q4" → "Kvartalsmöte Försäljning"
"Personalfest på kontoret" → "Personalfest På Kontoret"
"Föreläsning om AI teknologi" → "Föreläsning Om AI"
"Tandvård - rengöring" → "Tandvård Rengöring"
"Bilbesiktning Volvo" → "Bilbesiktning Volvo"

FINNISH LANGUAGE & SLANG EXAMPLES (5 words preferred, OUTPUT IN FINNISH):
"Kokous kehitystiimin kanssa klo 10" → "Kokous Kehitystiimin Kanssa"
"Kahvitauko toimistolla aamulla" → "Kahvitauko Toimistolla"
"Tapaaminen pomojen kanssa" → "Tapaaminen Pomojen Kanssa"
"Hammaslääkäri klo 15 keskustassa" → "Hammaslääkäri Klo 15"
"Äidin syntymäpäivä kotona" → "Äidin Syntymäpäivä"
"Lukemista tenttiin matematiikka" → "Lukemista Tenttiin"
"Ruokaostokset töiden jälkeen" → "Ruokaostokset Töiden Jälkeen"
"Treenit salilla klo 18" → "Treenit Salilla"
"Lääkärikäynti terveystarkastus" → "Lääkärikäynti Terveystarkastus"
"Työhaastattelu Nokialla Espoossa" → "Työhaastattelu Nokialla"
"Illallinen perheen kanssa" → "Illallinen Perheen Kanssa"
"Etätyö kotoa tänään" → "Etätyö Kotoa"
"Matematiikan opetus luokka 5" → "Matematiikan Opetus"
"Soitto mummille illalla" → "Soitto Mummille"
"Asunnon siivous viikonloppuna" → "Asunnon Siivous"
"Viikkokokous projektiryhmä Beta" → "Viikkokokous Projektiryhmä Beta"
"Kvartaalitapaaminen myynti Q4" → "Kvartaalitapaaminen Myynti"
"Henkilöstöjuhlat toimistossa" → "Henkilöstöjuhlat Toimistossa"
"Luento tekoälystä" → "Luento Tekoälystä"
"Hammashoito - puhdistus" → "Hammashoito Puhdistus"
"Auton katsastus huolto" → "Auton Katsastus"
"Bileet Pekan luona" → "Bileet Pekan Luona"
"Synttärikahvit toimistolla" → "Synttärikahvit Toimistolla"

ENGLISH LANGUAGE EXAMPLES (5 words preferred, OUTPUT IN ENGLISH):
"Weekly Team Standup Meeting - Project Alpha Q4" → "Project Alpha Team Standup"
"Dentist Appointment - Dr. Smith at 3pm Room 205" → "Dentist Appointment With Dr Smith"
"Sarah's Birthday Party Celebration at Restaurant" → "Sarah's Birthday Party"
"Q4 Sales Review Meeting with Leadership Team" → "Q4 Sales Leadership Meeting"
"Flight to New York - Delta Airlines AA1234" → "Flight To New York"
"Coffee with John to discuss project updates" → "Coffee With John"
"Annual Performance Review - HR Department" → "Annual Performance Review"
"Python Programming Workshop - Advanced Level" → "Advanced Python Programming Workshop"
"Client Presentation - Final Project Deliverable" → "Final Client Project Presentation"
"🎂 Birthday Party for Emma at home" → "🎂 Emma's Birthday Party"
"📊 Monthly Sales Meeting with Team" → "📊 Monthly Sales Meeting"
"🏥 Doctor Appointment at 2pm" → "🏥 Doctor Appointment"
"✈️ Flight to Paris - Air France" → "✈️ Flight To Paris"
"🍽️ Dinner with Friends at Italian Restaurant" → "🍽️ Dinner With Friends"

COLLOQUIAL & SLANG RECOGNITION:
"Plugga" = Study
"Fika" = Coffee break
"Träff" = Meeting
"Treenit" = Workout
"Bileet" = Party
"Synttärit/Syndet" = Birthday
"Mötesdjur" = Meeting (humorous)
"Kaffepaus" = Coffee break
"Kahvitauko" = Coffee break
"Ruokaostokset" = Grocery shopping
"Henkkareita" = ID/Documents
"Kämpän siivous" = Apartment cleaning

MORE QUALITY EXAMPLES (5 words preferred, MAINTAIN ORIGINAL LANGUAGE):
ENGLISH: "Weekly Team Standup Meeting - Project Alpha Q4" → "Project Alpha Team Standup"
ENGLISH: "Dentist Appointment - Dr. Smith at 3pm Room 205" → "Dentist Appointment With Dr Smith"
ENGLISH: "Sarah's Birthday Party Celebration at Restaurant" → "Sarah's Birthday Party"
ENGLISH: "Q4 Sales Review Meeting with Leadership Team" → "Q4 Sales Leadership Meeting"
ENGLISH: "Flight to New York - Delta Airlines AA1234" → "Flight To New York"
ENGLISH: "Coffee with John to discuss project updates" → "Coffee Meeting With John"
ENGLISH: "Annual Performance Review - HR Department" → "Annual Performance Review"
ENGLISH: "Python Programming Workshop - Advanced Level" → "Advanced Python Programming Workshop"
ENGLISH: "Client Presentation - Final Project Deliverable" → "Final Client Project Presentation"
ENGLISH: "🎂 Birthday Party for Emma at home" → "🎂 Emma's Birthday Party"
ENGLISH: "📊 Monthly Sales Meeting with Team" → "📊 Monthly Sales Meeting"
ENGLISH: "🏥 Doctor Appointment at 2pm" → "🏥 Doctor Appointment"
ENGLISH: "✈️ Flight to Paris - Air France" → "✈️ Flight To Paris"
ENGLISH: "🍽️ Dinner with Friends at Italian Restaurant" → "🍽️ Dinner With Friends"
SWEDISH: "Veckomöte med projektgrupp Alpha kvartal 4" → "Veckomöte Projektgrupp Alpha"
FINNISH: "Viikkokokous projektiryhmä Beta neljännes 4" → "Viikkokokous Projektiryhmä Beta"

Return ONLY the simplified title in the ORIGINAL language, nothing else."""

            # Try with higher temperature first for creativity, then lower if needed
            for attempt in range(2):
                response = self.client.chat.completions.create(
                    model="gpt-4.1-nano",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Simplify this calendar event title (keep it in its original language - English, Swedish, or Finnish): {title}"}
                    ],
                    max_tokens=150,  # Increased for 5-word titles
                    temperature=0.2 if attempt == 0 else 0.05,
                    top_p=0.8,
                    frequency_penalty=0.1,
                    presence_penalty=0.1
                )
                
                simplified = response.choices[0].message.content.strip()
                
                # Validate and clean the response
                if self._validate_simplified_title(simplified, title):
                    return self._clean_title(simplified)
                
                logger.debug(f"Attempt {attempt + 1} failed validation: '{simplified}', retrying...")
            
            # If both attempts failed, use fallback
            logger.warning(f"OpenAI failed validation after 2 attempts for '{title}', using fallback")
            return self._fallback_simplify(title)
            
        except Exception as e:
            logger.warning(f"OpenAI API error for title '{title}': {e}")
            return self._fallback_simplify(title)

    def _validate_simplified_title(self, simplified: str, original: str) -> bool:
        """Validate that the simplified title meets our requirements."""
        if not simplified:
            return False
        
        # Clean the title for validation
        cleaned = self._clean_title(simplified)
        words = cleaned.split()
        
        # Remove emojis for word count
        text_words = []
        for word in words:
            # Remove emojis from word for counting
            clean_word = ''.join(char for char in word if ord(char) < 0x1F600 or ord(char) > 0x1F9FF)
            if clean_word.strip():
                text_words.append(clean_word.strip())
        
        # Check word count (max 5 words of actual text)
        # For naturally short titles (1 word), keep as-is if not meaningless
        if len(text_words) > 5:
            logger.debug(f"Title too long: {len(text_words)} words")
            return False
        
        if len(text_words) < 1:
            logger.debug(f"Title too short: {len(text_words)} words")
            return False
        
        # Check for meaningless responses (in any language)
        meaningless = ['event', 'title', 'calendar', 'appointment', 'meeting only', 
                      'evenemang', 'titel', 'kalender', 'möte',
                      'tapahtuma', 'otsikko', 'kalenteri', 'kokous']
        if cleaned.lower().strip() in meaningless:
            logger.debug(f"Meaningless title: '{cleaned}'")
            return False
        
        return True

    def _clean_title(self, title: str) -> str:
        """Clean and format the title properly."""
        # Remove extra quotes, brackets, and formatting
        cleaned = title.strip('"\'`[]{}()')
        
        # Remove common prefixes that might be added
        prefixes_to_remove = ['simplified:', 'title:', 'english:', 'result:']
        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        
        # Ensure proper spacing around emojis
        cleaned = re.sub(r'([^\s])(\U0001F600-\U0001F64F|\U0001F300-\U0001F5FF|\U0001F680-\U0001F6FF|\U0001F1E0-\U0001F1FF|\U00002600-\U000027BF|\U0001f900-\U0001f9ff)', r'\1 \2', cleaned)
        cleaned = re.sub(r'(\U0001F600-\U0001F64F|\U0001F300-\U0001F5FF|\U0001F680-\U0001F6FF|\U0001F1E0-\U0001F1FF|\U00002600-\U000027BF|\U0001f900-\U0001f9ff)([^\s])', r'\1 \2', cleaned)
        
        # Clean up multiple spaces
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned

    def _fallback_simplify(self, title: str) -> str:
        """Enhanced fallback pattern-based simplification when OpenAI is unavailable."""
        try:
            # Extract emojis first to preserve them
            emojis = self._extract_emojis(title)
            
            # Extract key terms with better international support
            key_terms = self._extract_key_terms_fallback(title)
            
            # Build simplified title in original language
            words = []
            
            # Start with emojis if present
            if emojis:
                emoji_str = ''.join(emojis[:1])  # Limit to 1 emoji to save space
                words.append(emoji_str)
            
            # Add key terms from the original title (preserving original language)
            for term in key_terms:
                if len(words) >= 5:  # Updated to 5 words
                    break
                if len(term) > 1:
                    words.append(term.title())
            
            # If we don't have enough words, use first few words from title
            # Aim for at least 3 words for better context
            if len(words) < 3:
                additional = self._extract_fallback_words(title)
                words_lower = {w.lower() for w in words}  # Create set once for O(1) lookups
                for word in additional:
                    if len(words) >= 5:
                        break
                    # Avoid duplicates
                    if word.lower() not in words_lower:
                        words.append(word.title())
                        words_lower.add(word.lower())
            
            # Final check: if still less than 3 words, add more from original
            if len(words) < 3:
                # Split original and take first meaningful words not already included
                punctuation = ".,!?()[]{}"
                original_words = [w.strip(punctuation) for w in title.split() if len(w.strip(punctuation)) > 1]
                words_lower = {w.lower() for w in words}  # Create set once for O(1) lookups
                for word in original_words:
                    if len(words) >= 5:
                        break
                    if word.lower() not in words_lower:
                        words.append(word.title())
                        words_lower.add(word.lower())
            
            # Ensure we have at least one word
            if not words:
                return "Event"
            
            result = " ".join(words[:5])  # Updated to 5 words max
            return self._clean_title(result)
            
        except Exception as e:
            logger.warning(f"Enhanced fallback simplification failed for '{title}': {e}")
            return self._basic_fallback(title)

    def _basic_fallback(self, title: str) -> str:
        """Ultimate basic fallback."""
        try:
            emojis = self._extract_emojis(title)
            words = title.split()[:5]  # Updated to 5 words
            clean_words = [word.strip(".,!?()[]{}") for word in words if word.strip() and len(word) > 1]
            
            # If we have emojis, prepend them
            if emojis:
                emoji_str = ''.join(emojis[:1])
                result = [emoji_str] + clean_words[:4]  # Leave room for emoji
            else:
                result = clean_words
                
            return " ".join(result) if result else "Event"
        except:
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
        # Clean and tokenize, but preserve emojis
        # Remove punctuation but keep emojis and alphanumeric characters including Nordic characters
        cleaned = re.sub(r'[^\w\s\-åäöÅÄÖ\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001f900-\U0001f9ff\U0001f600-\U0001f64f]', ' ', title)
        words = [w.strip() for w in cleaned.split() if w.strip() and len(w) > 1]
        
        # Enhanced noise words with Swedish and Finnish common words
        noise_words = {
            'the', 'and', 'with', 'for', 'meeting', 'call', 'at', 'on', 'in',
            'med', 'och', 'för', 'på', 'i', 'av', 'till', 'från', 'det', 'den', 'är', 'att',
            'ja', 'kanssa', 'että', 'on', 'se', 'tai', 'kun', 'klo', 'kl', 'time', 'tid'
        }
        filtered = [w for w in words if w.lower() not in noise_words]
        
        # Prioritize capitalized words, words with emojis, and longer words
        # Also give bonus to Nordic-specific terms
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
            # Bonus for words with emojis
            if any(ord(char) > 0x1F600 for char in w):
                score += 10
            # Bonus for Nordic terms
            if w.lower() in nordic_bonus_terms:
                score += 8
            # Bonus for names (capitalized non-common words)
            if w[0].isupper() and len(w) > 3 and w.lower() not in noise_words:
                score += 3
            scored.append((w, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return [word for word, score in scored[:5]]  # Updated to return up to 5 terms

    def _extract_fallback_words(self, title: str) -> list:
        """Extract words as ultimate fallback."""
        # Look for capitalized words first
        caps_words = re.findall(r'\b[A-Z][a-z]+\b', title)
        if caps_words:
            return caps_words[:3]
        
        # Just take first few meaningful words
        words = [w for w in title.split() if len(w) > 2]
        return words[:3]

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
