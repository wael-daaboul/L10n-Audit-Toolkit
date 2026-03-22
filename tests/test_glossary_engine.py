import pytest
from pathlib import Path
from core.glossary_engine import load_glossary_rules, apply_text_replacements

def test_load_glossary_rules_success(tmp_path):
    glossary = {
        "terms": [
            {"term_en": "Customer", "approved_ar": "عميل", "forbidden_ar": ["زبون"]},
            {"term_en": "Driver", "approved_ar": "كابتن", "forbidden_ar": ["سائق", "دريفر"]}
        ]
    }
    path = tmp_path / "glossary.json"
    import json
    path.write_text(json.dumps(glossary, ensure_ascii=False), encoding="utf-8")
    
    rules = load_glossary_rules(path)
    assert rules["زبون"] == "عميل"
    assert rules["سائق"] == "كابتن"
    assert rules["دريفر"] == "كابتن"
    assert len(rules) == 3

def test_apply_text_replacements_whole_word():
    rules = {"زبون": "عميل"}
    text = "مرحبا يا زبون العزيز"
    
    # Simple replacement
    assert apply_text_replacements(text, rules) == "مرحبا يا عميل العزيز"
    
    # Substring should NOT match if surrounded by word characters
    # (Arabic words are \w)
    # زبونا should NOT match
    assert apply_text_replacements("زبونا العزيز", rules) == "زبونا العزيز"
    
    # But surrounded by punctuation should match
    assert apply_text_replacements("يا زبون!", rules) == "يا عميل!"
