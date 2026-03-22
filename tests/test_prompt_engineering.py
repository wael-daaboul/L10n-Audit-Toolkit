from ai.prompts import get_review_prompt

def test_prompt_contains_new_instructions():
    batch = [{"key": "k1", "source": "Add Address", "current_translation": "العنوان", "identified_issue": "imperative"}]
    prompt = get_review_prompt(batch)
    
    assert "Mobile UIs" in prompt
    assert "Strict Brevity" in prompt
    assert "Smart Suggestions" in prompt
    assert "{variables}" in prompt
    assert "Arabic noun" in prompt
    assert "Add Address" in prompt
    assert "العنوان" in prompt
