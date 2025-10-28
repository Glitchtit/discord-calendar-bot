"""
Test suite for AI title parser improvements.
Tests that the parser correctly prioritizes meaningful content over codes.
"""
import os
import sys

# Ensure OPENAI_API_KEY is not set for these tests (testing fallback)
os.environ['OPENAI_API_KEY'] = ''

from ai_title_parser import simplify_event_title


def test_swedish_course_with_codes():
    """Test the main example from the issue - Swedish course with multiple codes."""
    title = "2526H.Arbete inom el- och automationsbranschen Elgrunder (230.1) (AM25H/EM25H)"
    result = simplify_event_title(title)
    
    # Should prioritize meaningful words, not codes
    assert "am25h" not in result.lower(), f"Code AM25H should not appear in result: {result}"
    assert "em25h" not in result.lower(), f"Code EM25H should not appear in result: {result}"
    assert "2526" not in result, f"Code 2526H should not appear in result: {result}"
    assert "230" not in result, f"Code 230.1 should not appear in result: {result}"
    
    # Should contain meaningful words
    assert "arbete" in result.lower() or "automation" in result.lower() or "elgrunder" in result.lower(), \
        f"Result should contain meaningful subject words: {result}"
    
    print(f"✓ Swedish course test passed: '{title}' → '{result}'")


def test_swedish_basic_course():
    """Test Swedish basic course title."""
    title = "GRU101-Grundläggande svenska (Rum 3.14)"
    result = simplify_event_title(title)
    
    # Course code should be removed
    assert "gru101" not in result.lower(), f"Course code GRU101 should not appear: {result}"
    assert "3.14" not in result, f"Room number should not appear: {result}"
    
    # Should contain meaningful words
    assert "grundläggande" in result.lower() or "svenska" in result.lower(), \
        f"Result should contain subject words: {result}"
    
    print(f"✓ Swedish basic course test passed: '{title}' → '{result}'")


def test_swedish_math_course():
    """Test Swedish math course with codes in parentheses."""
    title = "MAT205.Avancerad matematik för ingenjörer (A1234/B5678)"
    result = simplify_event_title(title)
    
    # Codes should be removed or appear at the end if present at all
    result_words = result.split()
    # Check that codes are not in the first 2 words (they're deprioritized)
    first_two_words = ' '.join(result_words[:2]).lower()
    assert "a1234" not in first_two_words, f"Code A1234 should be deprioritized: {result}"
    assert "b5678" not in result.lower(), f"Code B5678 should not appear: {result}"
    assert "mat205" not in first_two_words, f"Course code MAT205 should be deprioritized: {result}"
    
    # Should contain meaningful words in prominent positions (first 3 words)
    first_three_words = ' '.join(result_words[:3]).lower()
    assert any(word in first_three_words for word in ["avancerad", "matematik", "ingenjörer"]), \
        f"Result should prioritize subject words: {result}"
    
    print(f"✓ Swedish math course test passed: '{title}' → '{result}'")


def test_swedish_physics_lecture():
    """Test Swedish physics lecture with room number."""
    title = "FYS301 - Kvantmekanik (Sal B205) Föreläsning 5"
    result = simplify_event_title(title)
    
    # Course code should be removed or deprioritized (not in first 2 words)
    result_words = result.split()
    first_two_words = ' '.join(result_words[:2]).lower()
    assert "fys301" not in first_two_words, f"Course code should be deprioritized: {result}"
    assert "b205" not in first_two_words, f"Room code should be deprioritized: {result}"
    
    # Should contain meaningful words in prominent positions
    first_three_words = ' '.join(result_words[:3]).lower()
    assert "kvantmekanik" in first_three_words or "föreläsning" in first_three_words, \
        f"Result should prioritize lecture subject: {result}"
    
    print(f"✓ Swedish physics lecture test passed: '{title}' → '{result}'")


def test_english_cs_course():
    """Test English computer science course."""
    title = "CS101-Introduction to Computer Science (Room 301)"
    result = simplify_event_title(title)
    
    # Course code should be removed or deprioritized (not in first 2 words)
    result_words = result.split()
    first_two_words = ' '.join(result_words[:2]).lower()
    assert "cs101" not in first_two_words, f"Course code should be deprioritized: {result}"
    assert "301" not in first_two_words, f"Room number should be deprioritized: {result}"
    
    # Should contain meaningful words in prominent positions
    first_three_words = ' '.join(result_words[:3]).lower()
    assert any(word in first_three_words for word in ["introduction", "computer", "science"]), \
        f"Result should prioritize course subject: {result}"
    
    print(f"✓ English CS course test passed: '{title}' → '{result}'")


def test_english_math_course():
    """Test English math course with codes."""
    title = "MATH205.Advanced Calculus for Engineers (A1234/B5678)"
    result = simplify_event_title(title)
    
    # Codes should be removed or deprioritized (not in first 2 words)
    result_words = result.split()
    first_two_words = ' '.join(result_words[:2]).lower()
    assert "a1234" not in first_two_words, f"Code A1234 should be deprioritized: {result}"
    assert "b5678" not in result.lower(), f"Code B5678 should not appear: {result}"
    assert "math205" not in first_two_words, f"Course code should be deprioritized: {result}"
    
    # Should contain meaningful words in prominent positions
    first_three_words = ' '.join(result_words[:3]).lower()
    assert any(word in first_three_words for word in ["advanced", "calculus", "engineers"]), \
        f"Result should prioritize course subject: {result}"
    
    print(f"✓ English math course test passed: '{title}' → '{result}'")


def test_word_count():
    """Test that results have appropriate word count (3-5 words)."""
    test_titles = [
        "2526H.Arbete inom el- och automationsbranschen Elgrunder (230.1) (AM25H/EM25H)",
        "CS101-Introduction to Computer Science (Room 301)",
        "Weekly Team Standup Meeting - Project Alpha Q4"
    ]
    
    for title in test_titles:
        result = simplify_event_title(title)
        word_count = len(result.split())
        assert 1 <= word_count <= 5, \
            f"Result should have 1-5 words, got {word_count}: '{result}' from '{title}'"
    
    print(f"✓ Word count test passed")


def test_no_empty_results():
    """Test that we always get a non-empty result."""
    test_titles = [
        "123456",
        "(A1234)",
        "CS101",
        "",
        "   "
    ]
    
    for title in test_titles:
        result = simplify_event_title(title)
        assert result and result.strip(), \
            f"Should always get a non-empty result, got '{result}' from '{title}'"
    
    print(f"✓ No empty results test passed")


def run_all_tests():
    """Run all tests and report results."""
    print("Running AI Title Parser Tests\n" + "="*50 + "\n")
    
    tests = [
        test_swedish_course_with_codes,
        test_swedish_basic_course,
        test_swedish_math_course,
        test_swedish_physics_lecture,
        test_english_cs_course,
        test_english_math_course,
        test_word_count,
        test_no_empty_results,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} ERROR: {e}")
            failed += 1
    
    print("\n" + "="*50)
    print(f"Results: {passed} passed, {failed} failed")
    
    if failed > 0:
        sys.exit(1)
    else:
        print("\nAll tests passed! ✓")
        sys.exit(0)


if __name__ == "__main__":
    run_all_tests()
