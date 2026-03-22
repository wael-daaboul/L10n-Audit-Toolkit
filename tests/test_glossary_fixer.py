import pytest
from pathlib import Path
from fixes.apply_glossary_fixes import apply_glossary_to_data
from conftest import write_json

def test_apply_glossary_to_data_replacements():
    rules = {"زبون": "عميل", "سائق": "كابتن"}
    # 'السائق' won't match 'سائق' because it's whole-word and 'السائق' is its own word
    data = {"k1": "يا زبون العزيز", "k2": "سائق وصل", "k3": "كابتن سارة"}
    
    updated, count = apply_glossary_to_data(data, rules)
    assert count == 2
    assert updated["k1"] == "يا عميل العزيز"
    assert updated["k2"] == "كابتن وصل"

def test_apply_glossary_to_data_whole_word_boundary():
    rules = {"زبون": "عميل"}
    data = {"k1": "زبون", "k2": "زبونا"}
    
    updated, count = apply_glossary_to_data(data, rules)
    assert count == 1
    assert updated["k1"] == "عميل"
    assert updated["k2"] == "زبونا" # No replacement here as 'زبون' isn't a whole word.

def test_fixer_round_trip(tmp_path):
    from fixes.apply_glossary_fixes import apply_glossary_to_data
    target = tmp_path / "ar.json"
    # Correct order: write_json(path, payload)
    write_json(target, {"welcome": "يا زبون"})
    
    rules = {"زبون": "عميل"}
    import json
    data = json.loads(target.read_text(encoding="utf-8"))
    
    updated, count = apply_glossary_to_data(data, rules)
    assert count == 1
    assert updated["welcome"] == "يا عميل"
    
    # Save back
    target.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    assert "يا عميل" in target.read_text(encoding="utf-8")
