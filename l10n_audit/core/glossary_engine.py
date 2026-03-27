import json
import re
from pathlib import Path
from typing import Any

def load_glossary_rules(glossary_path: Path) -> dict[str, str]:
    """Parse glossary.json and return a mapping of forbidden_ar to approved_ar."""
    if not glossary_path.exists():
        return {}
        
    try:
        data = json.loads(glossary_path.read_text(encoding="utf-8"))
        rules = {}
        for entry in data.get("terms", []):
            approved = entry.get("approved_ar")
            if not approved:
                continue
            
            forbidden_list = entry.get("forbidden_ar", [])
            for forbidden in forbidden_list:
                if forbidden:
                    rules[forbidden] = approved
        return rules
    except Exception:
        return {}

def apply_text_replacements(text: str, rules: dict[str, str]) -> str:
    """Apply forbidden term replacements using whole-word matching for Arabic."""
    if not text or not rules:
        return text
    
    # Sort rules by length descending to avoid partial matching issues 
    # (though whole-word matching helps)
    sorted_forbidden = sorted(rules.keys(), key=len, reverse=True)
    
    result = text
    for forbidden in sorted_forbidden:
        approved = rules[forbidden]
        # Regex for whole word in Arabic: 
        # Boundary is start/end of string or non-word/non-Arabic characters
        # For simplicity, we can use (?<!\w)forbidden(?!\w) but Arabic might be tricky.
        # Standard \b works in most modern engines for Unicode if set correctly.
        # However, Arabic characters are 'word' characters.
        pattern = re.compile(rf"(?<!\w){re.escape(forbidden)}(?!\w)", re.UNICODE)
        result = pattern.sub(approved, result)
        
    return result


def validate_item(item: dict, glossary_data: dict) -> tuple[bool, list[str]]:
    """
    Validates a single translation item against the glossary.
    Returns (is_valid, list_of_errors).
    """
    from l10n_audit.ai.verification import validate_glossary_compliance
    
    source = item.get("source", "")
    suggestion = item.get("suggestion", "")
    
    if not source or not suggestion:
        return True, []
        
    is_valid, error = validate_glossary_compliance(suggestion, source, glossary_data)
    if not is_valid:
        return False, [error]
    return True, []
