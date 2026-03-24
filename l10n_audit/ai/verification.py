import re
import logging

def check_placeholders(source, suggestion):
    """
    Checks if all placeholders in the source are present in the suggestion.
    Supports: {name}, %s, %(count)d, etc.
    """
    # Simple brackets: {name}
    source_placeholders = set(re.findall(r"\{[^}]+\}", source))
    suggest_placeholders = set(re.findall(r"\{[^}]+\}", suggestion))
    
    if not source_placeholders.issubset(suggest_placeholders):
        missing = source_placeholders - suggest_placeholders
        return False, f"Missing placeholders: {', '.join(missing)}"
    
    # Classic printf style: %s, %d, %(count)s
    printf_regex = r"%(\([^)]+\))?[-#0 +]*[\d\.]*[hlL]*[diouxXeEfFgGcrs%]"
    source_printf = set(m.group(0) for m in re.finditer(printf_regex, source))
    suggest_printf = set(m.group(0) for m in re.finditer(printf_regex, suggestion))
    
    if not source_printf.issubset(suggest_printf):
        missing = source_printf - suggest_printf
        return False, f"Printf-style placeholders mismatch: missing {', '.join(missing)}"
    
    return True, ""

def check_newlines(source, suggestion):
    """
    Checks if basic newline occurrences are drastically different.
    We don't want the AI to merge lines if layout depends on them.
    """
    source_newlines = source.count("\n") + source.count("\\n")
    suggest_newlines = suggestion.count("\n") + suggestion.count("\\n")
    
    if suggest_newlines < source_newlines:
        return False, f"Missing newlines: expected at least {source_newlines}, got {suggest_newlines}"
    
    return True, ""

def check_html(source, suggestion):
    """
    Checks if HTML tags are intact.
    """
    source_tags = set(re.findall(r"<[^>]+>", source))
    suggest_tags = set(re.findall(r"<[^>]+>", suggestion))
    
    if not source_tags.issubset(suggest_tags):
        missing = source_tags - suggest_tags
        return False, f"Missing HTML tags: {', '.join(missing)}"
    
    return True, ""

class GlossaryViolationError(Exception):
    """Raised when an AI suggestion violates glossary rules."""
    pass


def validate_glossary_compliance(suggestion: str, source_text: str, glossary: dict) -> tuple[bool, str]:
    """Strictly validates if the suggestion complies with the provided glossary.
    
    Returns (True, "") if compliant, (False, "reason") otherwise.
    """
    if not glossary:
        return True, ""

    # Compile term patterns for source text matching
    glossary_terms = []
    for term in glossary.get("terms", []):
        if isinstance(term, dict) and term.get("term_en") and term.get("approved_ar"):
            glossary_terms.append({
                "term_en": str(term["term_en"]),
                "approved_ar": str(term["approved_ar"]),
                "forbidden_ar": [str(i) for i in term.get("forbidden_ar", []) if i],
                "pattern": re.compile(rf"(?<![A-Za-z]){re.escape(str(term['term_en']))}(?![A-Za-z])", re.IGNORECASE)
            })

    # 1. Global forbidden terms (unconditional)
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            forbidden = str(item.get("forbidden_ar", ""))
            if forbidden and forbidden in suggestion:
                use_instead = item.get("use_instead", "an approved term")
                return False, f"Uses forbidden global term '{forbidden}'. Use '{use_instead}' instead."

    # 2. Key-term mapping based on source text
    for term in glossary_terms:
        if term["pattern"].search(source_text):
            approved_ar = term["approved_ar"]
            # Strict: Approved term MUST be in the suggestion if English uses it
            if approved_ar not in suggestion:
                return False, f"Missing approved glossary term '{approved_ar}' for English term '{term['term_en']}'."
            
            # Strict: Forbidden terms MUST NOT be in the suggestion
            for forbidden in term["forbidden_ar"]:
                if forbidden in suggestion:
                    return False, f"Uses forbidden glossary term '{forbidden}' for English term '{term['term_en']}'. Use '{approved_ar}' instead."

    return True, ""


def verify_batch_fixes(original_batch, ai_fixes, glossary=None):
    """
    Verifies a batch of AI suggestions.
    Checks placeholders, newlines, HTML tags, and GLOSSARY compliance.
    """
    verified_fixes = []
    source_by_key = {item["key"]: item["source_text"] for item in original_batch if "source_text" in item}
    # Fallback to 'source' if 'source_text' is missing
    if not source_by_key:
        source_by_key = {item["key"]: item.get("source", "") for item in original_batch}
        
    target_by_key = {item["key"]: item.get("current_translation", "") for item in original_batch}
    
    for fix in ai_fixes:
        key = fix.get("key")
        suggestion = fix.get("suggestion")
        
        if not key or not suggestion or key not in source_by_key:
            continue
            
        source_text = source_by_key[key]
        target_text = target_by_key[key]
        
        # If suggestion is identical, skip
        if suggestion.strip() == target_text.strip():
            continue
            
        # Basic Verification
        v_tasks = [
            check_placeholders(source_text, suggestion),
            check_newlines(source_text, suggestion),
            check_html(source_text, suggestion)
        ]
        
        # Glossary Verification
        if glossary:
            v_tasks.append(validate_glossary_compliance(suggestion, source_text, glossary))
        
        failed = [msg for ok, msg in v_tasks if not ok]
        
        if not failed:
            verified_fixes.append({
                "key": key,
                "verified": True,
                "issue_type": "ai_suggestion",
                "severity": "info",
                "message": f"AI Suggestion: {fix.get('reason', '')}",
                "source": source_text,
                "target": target_text,
                "suggestion": suggestion,
                "extra": {"verified": True} # For backward compatibility with some engines
            })
        else:
            logging.debug(f"AI Suggestion for {key} rejected by verification: {failed}")
            
    return verified_fixes

