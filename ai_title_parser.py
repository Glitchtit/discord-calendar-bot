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
        
        # Enhanced fallback patterns with international terms
        self.fallback_patterns = {
            'meeting': r'\b(meeting|meet|call|conference|sync|standup|retrospective|review|möte|utveckling|reunión|réunion|besprechung|vergadering)\b',
            'appointment': r'\b(appointment|appt|visit|consultation|checkup|termin|cita|rendez-vous|afspraak)\b',
            'class': r'\b(class|lecture|lesson|training|workshop|seminar|EM|GT|klass|lektion|curso|cours|unterricht|les)\b',
            'event': r'\b(event|party|celebration|ceremony|launch|evenemang|evento|événement|veranstaltung|evenement)\b',
            'deadline': r'\b(deadline|due|submit|delivery|finish|frist|plazo|échéance|deadline)\b',
            'interview': r'\b(interview|screening|hiring|intervju|entrevista|entretien|vorstellungsgespräch|sollicitatiegesprek)\b',
            'lunch': r'\b(lunch|dinner|breakfast|meal|eat|lunch|almuerzo|déjeuner|mittagessen|ontbijt|middag)\b',
            'travel': r'\b(flight|travel|trip|vacation|holiday|resa|viaje|voyage|reise|reis|vakantie)\b',
            'birthday': r'\b(birthday|bday|anniversary|födelsedag|cumpleaños|anniversaire|geburtstag|verjaardag)\b',
            'reminder': r'\b(reminder|remind|follow.?up|todo|påminnelse|recordatorio|rappel|erinnerung|herinnering)\b',
            'work': r'\b(ansvarsarbetstid|undervisning|arbete|trabajo|travail|arbeit|werk)\b',
            'doctor': r'\b(doctor|medical|health|läkare|doctor|médecin|arzt|dokter|doktor)\b',
            'shopping': r'\b(shopping|store|buy|handla|compras|courses|einkaufen|winkelen)\b'
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
        Simplify an event title to maximum 3 words using OpenAI API.
        
        Args:
            original_title: The original event title
            
        Returns:
            Simplified title (max 3 words)
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
            system_prompt = """You are an expert at simplifying calendar event titles. Your task is to convert long, complex event titles into concise, clear titles that capture the essence of the event.

CRITICAL RULES:
1. ALWAYS output in English, regardless of input language
2. Maximum 3 words (but 2 words is often better)
3. Use title case (First Letter Capitalized)
4. Focus on the most important information
5. Remove unnecessary details like times, locations, specific room numbers, recurring indicators
6. Preserve the core meaning and purpose
7. If the original title contains emojis, preserve them in the simplified title
8. Translate non-English titles to English while maintaining meaning
9. Use common, clear English words that are easily understood
10. For work events, prefer generic terms over specific company jargon

Language Translation Examples:
"Möte med utvecklingsteam" → "Dev Meeting"
"Réunion équipe marketing" → "Marketing Meeting"
"Cita médica con Dr. García" → "Doctor Visit"
"Geburtstag von Anna" → "Anna's Birthday"
"Déjeuner avec clients" → "Client Lunch"
"Besprechung Projekt Alpha" → "Project Meeting"
"Ansvarsarbetstid hemma" → "Work Time"
"Undervisning matematik" → "Math Class"

Quality Examples:
"Weekly Team Standup Meeting - Project Alpha Q4" → "Team Standup"
"Dentist Appointment - Dr. Smith at 3pm Room 205" → "Dentist Visit"
"Sarah's Birthday Party Celebration at Restaurant" → "Sarah's Birthday"
"Q4 Sales Review Meeting with Leadership Team" → "Sales Review"
"Flight to New York - Delta Airlines AA1234" → "Flight NYC"
"Coffee with John to discuss project updates" → "Coffee John"
"Annual Performance Review - HR Department" → "Performance Review"
"Python Programming Workshop - Advanced Level" → "Python Workshop"
"Client Presentation - Final Project Deliverable" → "Client Presentation"
"🎂 Birthday Party for Emma at home" → "🎂 Emma's Birthday"
"📊 Monthly Sales Meeting with Team" → "📊 Sales Meeting"
"🏥 Doctor Appointment at 2pm" → "🏥 Doctor Visit"
"✈️ Flight to Paris - Air France" → "✈️ Flight Paris"
"🍽️ Dinner with Friends at Italian Restaurant" → "🍽️ Dinner Friends"
"Recurring: Daily Stand-up Meeting" → "Daily Standup"
"CANCELLED: Team Building Event" → "Team Building"
"Moved: Project Kickoff Meeting" → "Project Kickoff"

Return ONLY the simplified English title, nothing else."""

            # Try with higher temperature first for creativity, then lower if needed
            for attempt in range(2):
                response = self.client.chat.completions.create(
                    model="gpt-4.1-nano",  # More capable model (corrected)
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Simplify this calendar event title to English: {title}"}
                    ],
                    max_tokens=100,  # Increased token limit
                    temperature=0.3 if attempt == 0 else 0.1,  # Lower temperature for more focused output
                    top_p=0.9,
                    frequency_penalty=0.0,
                    presence_penalty=0.0
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
        
        # Check word count (max 3 words of actual text)
        if len(text_words) > 3:
            logger.debug(f"Title too long: {len(text_words)} words")
            return False
        
        # Check if it's mostly English (basic check)
        if not self._is_mostly_english(cleaned):
            logger.debug(f"Title not in English: '{cleaned}'")
            return False
        
        # Check for meaningless responses
        meaningless = ['event', 'title', 'calendar', 'appointment', 'meeting only']
        if cleaned.lower().strip() in meaningless:
            logger.debug(f"Meaningless title: '{cleaned}'")
            return False
        
        return True

    def _is_mostly_english(self, text: str) -> bool:
        """Basic check if text is mostly English."""
        # Remove emojis and punctuation for language detection
        clean_text = ''.join(char for char in text if char.isalpha() or char.isspace())
        clean_text = clean_text.strip()
        
        if not clean_text:
            return True  # If only emojis, consider valid
        
        # Check for common non-English characters
        non_english_chars = set('àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ' + 
                               'ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞŸ' +
                               'ßščřžýáíéóúůň' + 'ñáéíóúü')
        
        # If more than 30% non-English chars, likely not English
        total_alpha = sum(1 for c in clean_text if c.isalpha())
        non_english_count = sum(1 for c in clean_text if c in non_english_chars)
        
        if total_alpha > 0 and (non_english_count / total_alpha) > 0.3:
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
            
            # Detect event type using enhanced patterns
            event_type = self._detect_event_type_fallback(title)
            
            # Extract key terms with better international support
            key_terms = self._extract_key_terms_fallback(title)
            
            # Build simplified title
            words = []
            
            # Start with emojis if present
            if emojis:
                emoji_str = ''.join(emojis[:1])  # Limit to 1 emoji to save space
                words.append(emoji_str)
            
            # Add event type if detected and meaningful
            if event_type and event_type not in ['event', 'work']:
                if event_type == 'remote work':
                    words.append('Work')
                else:
                    words.append(event_type.replace('_', ' ').title())
            
            # Add key terms
            for term in key_terms:
                if len(words) >= 3:
                    break
                if term.lower() != event_type and len(term) > 1:
                    words.append(term.title())
            
            # If we don't have enough words, use first few words from title
            if len(words) < 2:
                additional = self._extract_fallback_words(title)
                for word in additional:
                    if len(words) >= 3:
                        break
                    if word.lower() not in [w.lower().replace('_', ' ') for w in words]:
                        words.append(word.title())
            
            # Ensure we have at least one word
            if not words:
                return "Event"
            
            result = " ".join(words[:3])
            return self._clean_title(result)
            
        except Exception as e:
            logger.warning(f"Enhanced fallback simplification failed for '{title}': {e}")
            return self._basic_fallback(title)

    def _basic_fallback(self, title: str) -> str:
        """Ultimate basic fallback."""
        try:
            emojis = self._extract_emojis(title)
            words = title.split()[:3]
            clean_words = [word.strip(".,!?()[]{}") for word in words if word.strip() and len(word) > 1]
            
            # If we have emojis, prepend them
            if emojis:
                emoji_str = ''.join(emojis[:1])
                result = [emoji_str] + clean_words[:2]
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
        """Extract key terms using simple pattern matching."""
        # Clean and tokenize, but preserve emojis
        # Remove punctuation but keep emojis and alphanumeric characters
        cleaned = re.sub(r'[^\w\s\-\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000027BF\U0001f900-\U0001f9ff\U0001f600-\U0001f64f]', ' ', title)
        words = [w.strip() for w in cleaned.split() if w.strip() and len(w) > 2]
        
        # Remove common noise words
        noise_words = {'the', 'and', 'with', 'for', 'meeting', 'call', 'at', 'on', 'in'}
        filtered = [w for w in words if w.lower() not in noise_words]
        
        # Prioritize capitalized words, words with emojis, and longer words
        scored = []
        for w in filtered:
            score = len(w)
            if w[0].isupper():
                score += 5
            # Bonus for words with emojis
            if any(ord(char) > 0x1F600 for char in w):
                score += 10
            scored.append((w, score))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return [word for word, score in scored[:3]]

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
