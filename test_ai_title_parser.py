"""
Test suite for AI title parser improvements.
Tests that the parser correctly prioritizes meaningful content over codes.
"""
import os
import sys

import pytest

# Ensure OPENAI_API_KEY is not set for these tests (testing fallback)
os.environ['OPENAI_API_KEY'] = ''

from ai_title_parser import simplify_event_title  # noqa: E402


class TestSwedishCourses:
    """Tests for Swedish course title simplification."""

    def test_course_with_multiple_codes(self):
        title = "2526H.Arbete inom el- och automationsbranschen Elgrunder (230.1) (AM25H/EM25H)"
        result = simplify_event_title(title)

        assert "am25h" not in result.lower(), f"Code am25h should not appear: {result}"
        assert "em25h" not in result.lower(), f"Code em25h should not appear: {result}"
        assert "2526" not in result, f"Code 2526H should not appear: {result}"
        assert "230" not in result, f"Code 230.1 should not appear: {result}"
        assert any(w in result.lower() for w in ["arbete", "automation", "elgrunder"]), \
            f"Should contain meaningful subject words: {result}"

    def test_basic_course(self):
        title = "GRU101-Grundläggande svenska (Rum 3.14)"
        result = simplify_event_title(title)

        assert "gru101" not in result.lower()
        assert "3.14" not in result
        assert any(w in result.lower() for w in ["grundläggande", "svenska"])

    def test_math_course_with_group_codes(self):
        title = "MAT205.Avancerad matematik för ingenjörer (A1234/B5678)"
        result = simplify_event_title(title)
        words = result.split()
        first_two = ' '.join(words[:min(2, len(words))]).lower()

        assert "a1234" not in first_two
        assert "b5678" not in result.lower()
        assert "mat205" not in first_two
        first_three = ' '.join(words[:min(3, len(words))]).lower()
        assert any(w in first_three for w in ["avancerad", "matematik", "ingenjörer"])

    def test_physics_lecture(self):
        title = "FYS301 - Kvantmekanik (Sal B205) Föreläsning 5"
        result = simplify_event_title(title)
        words = result.split()
        first_two = ' '.join(words[:min(2, len(words))]).lower()

        assert "fys301" not in first_two
        assert "b205" not in first_two
        first_three = ' '.join(words[:min(3, len(words))]).lower()
        assert "kvantmekanik" in first_three or "föreläsning" in first_three


class TestEnglishCourses:
    """Tests for English course title simplification."""

    def test_cs_course(self):
        title = "CS101-Introduction to Computer Science (Room 301)"
        result = simplify_event_title(title)
        words = result.split()
        first_two = ' '.join(words[:min(2, len(words))]).lower()

        assert "cs101" not in first_two
        assert "301" not in first_two
        first_three = ' '.join(words[:min(3, len(words))]).lower()
        assert any(w in first_three for w in ["introduction", "computer", "science"])

    def test_math_course(self):
        title = "MATH205.Advanced Calculus for Engineers (A1234/B5678)"
        result = simplify_event_title(title)
        words = result.split()
        first_two = ' '.join(words[:min(2, len(words))]).lower()

        assert "a1234" not in first_two
        assert "b5678" not in result.lower()
        assert "math205" not in first_two
        first_three = ' '.join(words[:min(3, len(words))]).lower()
        assert any(w in first_three for w in ["advanced", "calculus", "engineers"])


class TestOutputConstraints:
    """Tests for output format constraints."""

    @pytest.mark.parametrize("title", [
        "2526H.Arbete inom el- och automationsbranschen Elgrunder (230.1) (AM25H/EM25H)",
        "CS101-Introduction to Computer Science (Room 301)",
        "Weekly Team Standup Meeting - Project Alpha Q4",
    ])
    def test_word_count_between_1_and_5(self, title):
        result = simplify_event_title(title)
        word_count = len(result.split())
        assert 1 <= word_count <= 5, \
            f"Expected 1-5 words, got {word_count}: '{result}' from '{title}'"

    @pytest.mark.parametrize("title", [
        "123456",
        "(A1234)",
        "CS101",
        "",
        "   ",
    ])
    def test_never_returns_empty(self, title):
        result = simplify_event_title(title)
        assert result and result.strip(), \
            f"Should always return non-empty, got '{result}' from '{title}'"

