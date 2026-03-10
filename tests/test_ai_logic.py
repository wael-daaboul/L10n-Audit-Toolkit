import json
from ai.verification import check_placeholders, check_newlines, check_html
from ai.prompts import get_review_prompt

def test_verification_placeholders():
    # Valid
    ok, msg = check_placeholders("Hello {name}", "أهلاً {name}")
    assert ok is True
    
    # Missing
    ok, msg = check_placeholders("Hello {name}", "أهلاً")
    assert ok is False
    assert "Missing placeholders" in msg

    # Printf style
    ok, msg = check_placeholders("Count: %d", "العدد: %d")
    assert ok is True
    
    ok, msg = check_placeholders("Count: %d", "العدد: %s") # different type is still a mismatch in our simple regex
    assert ok is False

def test_verification_newlines():
    ok, msg = check_newlines("Line 1\\nLine 2", "سطر 1\\nسطر 2")
    assert ok is True
    
    ok, msg = check_newlines("Line 1\\nLine 2", "سطر 1 سطر 2")
    assert ok is False
    assert "Missing newlines" in msg

def test_verification_html():
    ok, msg = check_html("<b>Bold</b>", "<b>عريض</b>")
    assert ok is True
    
    ok, msg = check_html("<b>Bold</b>", "عريض")
    assert ok is False
    assert "Missing HTML tags" in msg

def test_prompt_generation():
    prompt = get_review_prompt("Hello", "أهلاً")
    assert "Hello" in prompt
    assert "أهلاً" in prompt
    assert "JSON" in prompt

if __name__ == "__main__":
    test_verification_placeholders()
    test_verification_newlines()
    test_verification_html()
    test_prompt_generation()
    print("AI Unit Tests Passed!")
