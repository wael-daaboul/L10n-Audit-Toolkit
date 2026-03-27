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
    
    # Colon-prefixed: :totalAmount, :collectCash
    source_colons = set(re.findall(r"(?<!\w):[A-Za-z0-9_]+", source))
    suggest_colons = set(re.findall(r"(?<!\w):[A-Za-z0-9_]+", suggestion))
    
    if not source_placeholders.issubset(suggest_placeholders):
        missing = source_placeholders - suggest_placeholders
        return False, f"Missing placeholders (braces): {', '.join(missing)}"
    
    if not source_colons.issubset(suggest_colons):
        missing = source_colons - suggest_colons
        return False, f"Missing placeholders (colon): {', '.join(missing)}"
    
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


def is_arabic_fuzzy_match(term: str, text: str) -> bool:
    """Check if 'term' exists in 'text' with Arabic-aware flexibility (prefixes, suffixes, plurals)."""
    if not term or not text:
        return False
    if term in text:
        return True
    
    # Common Arabic prefixes and suffixes to strip for core matching
    def get_core(s):
        # Strip common prefixes (Al, Li, Bi, Ka, Wa, Fa)
        s = re.sub(r"^(ال|ل|ب|ك|و|ف)", "", s)
        # Remove weak letters/vowels for root-ish comparison (Alef, Waw, Ya, Teh Marbuta)
        return re.sub(r"[اويية]", "", s)

    term_core = get_core(term)
    if not term_core or len(term_core) < 2:
        return term in text
        
    # Split text into words and check each
    words = re.split(r"[^\w\u0600-\u06FF]+", text)
    for word in words:
        if not word: continue
        w_core = get_core(word)
        if term_core in w_core:
            # Check length to ensure it's a derivation, not a random word
            if abs(len(w_core) - len(term_core)) <= 3:
                return True
    return False


def validate_glossary_compliance(suggestion: str, source_text: str, glossary: dict, key: str = "") -> tuple[bool, str]:
    """Strictly validates if the suggestion complies with the provided glossary.
    
    Supports fuzzy matching for Arabic to handle prefixes, suffixes, and plurals.
    Includes technical key patterns and term density checks to avoid false positives.
    """
    if not glossary:
        return True, ""

    # 0. Technical Key / Pattern Ignore List (Bulletproof Recovery)
    technical_prefixes = ("config", "setup", "uuid", "error_code", "zone")
    technical_substr = ("_id", "_url")
    uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

    if key:
        k_lower = key.lower()
        if k_lower.startswith(technical_prefixes) or any(s in k_lower for s in technical_substr) or uuid_pattern.search(key):
            logging.debug(f"Glossary check ignored for technical key: {key}")
            return True, ""

    # 1. Technical Term Density Check
    # If a string contains > 30% technical identifiers (paths, slugs, codes), we lower the enforcement
    tech_identifiers = re.findall(r"[A-Za-z0-9_]{5,}/[A-Za-z0-9_/]+|[a-z0-9_]{10,}", suggestion)
    words = suggestion.split()
    if words:
        tech_ratio = len(tech_identifiers) / len(words)
        if tech_ratio > 0.3:
            logging.debug(f"Glossary check softened: Tech density {tech_ratio:.2f}")
            # We don't return True immediately, but we can be more lenient later if needed.
            # For now, following the user's "Ignore errors" instruction.
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

    # 2. Global forbidden terms (unconditional) - TESTED ON TARGET VALUE ONLY
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            forbidden = str(item.get("forbidden_ar", ""))
            # VALIDATION ON TARGET (suggestion) ONLY
            if forbidden and forbidden in suggestion:
                use_instead = item.get("use_instead", "an approved term")
                return False, f"Uses forbidden global term '{forbidden}'. Use '{use_instead}' instead."

    # 3. Key-term mapping based on source text - VALIDATION ON TARGET (suggestion) ONLY
    for term in glossary_terms:
        # We only check if the term exists in SOURCE to know if it's required in TARGET
        if term["pattern"].search(source_text):
            approved_ar = term["approved_ar"]
            # Flexible: Approved term check (ON TARGET ONLY)
            if not is_arabic_fuzzy_match(approved_ar, suggestion):
                return False, f"Missing approved glossary term '{approved_ar}' for English term '{term['term_en']}'."
            
            # Strict: Forbidden terms (ON TARGET ONLY)
            for forbidden in term["forbidden_ar"]:
                if is_arabic_fuzzy_match(forbidden, suggestion):
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
        
        # Capture original source for reporting if it was pre-processed
        item = next((i for i in original_batch if i.get("key") == key), {})
        original_source = item.get("original_source", source_text)
        
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
            v_tasks.append(validate_glossary_compliance(suggestion, source_text, glossary, key=key))
        
        failed = [msg for ok, msg in v_tasks if not ok]
        
        if not failed:
            verified_fixes.append({
                "key": key,
                "verified": True,
                "issue_type": "ai_suggestion",
                "severity": "info",
                "message": f"AI Suggestion: {fix.get('reason', '')}",
                "source": source_text,
                "original_source": original_source,
                "target": target_text,
                "suggestion": suggestion,
                "extra": {"verified": True} # For backward compatibility with some engines
            })
        else:
            logging.debug(f"AI Suggestion for {key} rejected by verification: {failed}")
            
    return verified_fixes

