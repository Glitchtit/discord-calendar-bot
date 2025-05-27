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
        
        # Fallback patterns for when API is unavailable
        self.fallback_patterns = {
            'meeting': r'\b(meeting|meet|call|conference|sync|standup|retrospective|review)\b',
            'appointment': r'\b(appointment|appt|visit|consultation|checkup)\b',
            'class': r'\b(class|lecture|lesson|training|workshop|seminar)\b',
            'event': r'\b(event|party|celebration|ceremony|launch)\b',
            'deadline': r'\b(deadline|due|submit|delivery|finish)\b',
            'interview': r'\b(interview|screening|hiring)\b',
            'lunch': r'\b(lunch|dinner|breakfast|meal|eat)\b',
            'travel': r'\b(flight|travel|trip|vacation|holiday)\b',
            'birthday': r'\b(birthday|bday|anniversary)\b',
            'reminder': r'\b(reminder|remind|follow.?up|todo)\b'
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

    def _simplify_with_openai(self, title: str) -> str:
        """Use OpenAI API to intelligently simplify the title."""
        try:
            system_prompt = """You are an expert at simplifying calendar event titles. Your task is to convert long, complex event titles into concise 3-word maximum titles that capture the essence of the event.

Rules:
1. Maximum 3 words
2. Use title case (First Letter Capitalized)
3. Focus on the most important information
4. Remove unnecessary details like times, locations, recurring indicators
5. Preserve the core meaning and purpose

Examples:
"Weekly Team Standup Meeting - Project Alpha" → "Team Standup"
"Dentist Appointment - Dr. Smith at 3pm" → "Dentist Appointment"
"Sarah's Birthday Party Celebration" → "Sarah's Birthday"
"Q4 Sales Review Meeting with Leadership Team" → "Sales Review"
"Flight to New York - AA1234" → "Flight NYC"
"Coffee with John to discuss project updates" → "Coffee John"
"Annual Performance Review - HR Department" → "Performance Review"
"Lunch Break" → "Lunch"
"Python Programming Workshop - Advanced Level" → "Python Workshop"
"Client Presentation - Final Project Deliverable" → "Client Presentation"

Return ONLY the simplified title, nothing else."""

            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Simplify this calendar event title: {title}"}
                ],
                max_tokens=50,
                temperature=0.3
            )
            
            simplified = response.choices[0].message.content.strip()
            
            # Validate the response
            if not simplified or len(simplified.split()) > 3:
                logger.warning(f"OpenAI returned invalid response: '{simplified}', using fallback")
                return self._fallback_simplify(title)
            
            # Clean up any quotes or extra formatting
            simplified = simplified.strip('"\'`')
            
            return simplified
            
        except Exception as e:
            logger.warning(f"OpenAI API error for title '{title}': {e}")
            return self._fallback_simplify(title)

    def _fallback_simplify(self, title: str) -> str:
        """Fallback pattern-based simplification when OpenAI is unavailable."""
        try:
            # Detect event type using patterns
            event_type = self._detect_event_type_fallback(title)
            
            # Extract key terms
            key_terms = self._extract_key_terms_fallback(title)
            
            # Build simplified title
            words = []
            
            # Start with event type if detected
            if event_type and event_type not in ['event']:
                words.append(event_type.title())
            
            # Add key terms
            for term in key_terms:
                if len(words) >= 3:
                    break
                if term.lower() != event_type:
                    words.append(term.title())
            
            # If we don't have enough words, use first few words from title
            if len(words) < 2:
                additional = self._extract_fallback_words(title)
                for word in additional:
                    if len(words) >= 3:
                        break
                    if word.lower() not in [w.lower() for w in words]:
                        words.append(word.title())
            
            # Ensure we have at least one word
            if not words:
                return "Event"
            
            return " ".join(words[:3])
            
        except Exception as e:
            logger.warning(f"Fallback simplification failed for '{title}': {e}")
            # Ultimate fallback - just take first 3 words
            try:
                words = title.split()[:3]
                return " ".join(word.strip(".,!?()[]{}") for word in words if word.strip())
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
        # Clean and tokenize
        cleaned = re.sub(r'[^\w\s-]', ' ', title)
        words = [w.strip() for w in cleaned.split() if w.strip() and len(w) > 2]
        
        # Remove common noise words
        noise_words = {'the', 'and', 'with', 'for', 'meeting', 'call', 'at', 'on', 'in'}
        filtered = [w for w in words if w.lower() not in noise_words]
        
        # Prioritize capitalized words and longer words
        scored = [(w, len(w) + (5 if w[0].isupper() else 0)) for w in filtered]
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
