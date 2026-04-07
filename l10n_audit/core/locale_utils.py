#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("l10n_audit.core")

# Canonical mapping of audit source names to their primary locale
_SOURCE_LOCALE_MAP: Dict[str, str] = {
    "ar_locale_qc": "ar",
    "ar_semantic_qc": "ar",
    "en_locale_qc": "en",
    "grammar": "en",           # Standard Grammar Audit
    "en_grammar_audit": "en",  # Legacy fallback
    "ai_review": "ar",         # AI Review (usually target)
    "locale_qc": "en",         # Generic rules (usually source)
    "terminology": "ar",       # Terminology (usually target)
}

def normalized_non_empty_string(value: Any) -> Optional[str]:
    """Return stripped string if not empty, else None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None

def resolve_issue_locale(issue: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Canonical locale resolution for an audit issue.
    Returns (locale, source_of_determination). Locale is 'ar' or 'en' or None.
    """
    if not isinstance(issue, dict):
        return None, None

    # 1. Explicit locale field
    loc = normalized_non_empty_string(issue.get("locale"))
    if loc in {"ar", "en"}:
        return loc, "explicit"
    
    # 2. Source-based inference
    source = str(issue.get("source", "")).strip().lower()
    if source in _SOURCE_LOCALE_MAP:
        return _SOURCE_LOCALE_MAP[source], "source_mapping"
    
    # 3. Key prefix inference (e.g. 'ar.auth.failed')
    key = str(issue.get("key", "")).strip()
    if key:
        first_segment = key.split(".")[0].lower()
        if first_segment == "ar":
            return "ar", "key_prefix"
        if first_segment == "en":
            return "en", "key_prefix"

    # 4. File path inference
    file_path = str(issue.get("file_path") or issue.get("file") or "").strip().lower().replace("\\", "/")
    if file_path:
        if "/ar/" in file_path or file_path.endswith("ar.json"):
            return "ar", "file_path"
        if "/en/" in file_path or file_path.endswith("en.json"):
            return "en", "file_path"
    
    # 5. Code-based fallback
    code = str(issue.get("code", ""))
    if code == "AI_SUGGESTION":
        return "ar", "code_fallback"
    
    # 6. Contextual hints (if present)
    details = issue.get("details", {})
    loc_detail = normalized_non_empty_string(details.get("locale"))
    if loc_detail in {"ar", "en"}:
        return loc_detail, "details_context"

    return None, None

def get_value_smart(target_key: str, locale_data: Dict[str, Any]) -> Optional[str]:
    """
    Perform a smart lookup for a key in a potentially flattened locale mapping.
    Handles exact match, dot-notated match, and suffix matching for nested keys.
    """
    if not target_key or not locale_data:
        return None
        
    # 1. Direct hit
    if target_key in locale_data:
        val = locale_data[target_key]
        return str(val) if val is not None else None
        
    # 2. Suffix match (e.g. 'contact_with_us' matches 'messages.contact_with_us')
    # Use dot as separator to ensure we match a full segment
    search_suffix = f".{target_key}"
    for k, v in locale_data.items():
        if k.endswith(search_suffix):
            return str(v) if v is not None else None
            
    return None

def resolve_issue_current_value(issue: Dict[str, Any], locale_data: Optional[Dict[str, Any]] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Extract the original/source value for an issue.
    Returns (value, source_of_determination).
    """
    details = issue.get("details", {})
    
    # Priority list of fields
    candidates = [
        ("source_old_value", issue.get("source_old_value")),
        ("current_value", issue.get("current_value")),
        ("target", issue.get("target")),
        ("details.old", details.get("old")),
        ("issue.old", issue.get("old")),
        ("current_translation", issue.get("current_translation")),
    ]
    
    for source_name, raw_val in candidates:
        val = normalized_non_empty_string(raw_val)
        if val is not None:
            return val, source_name
            
    # Fallback: Smart Lookup using key if data is available
    if locale_data:
        key = normalized_non_empty_string(issue.get("key"))
        if key:
            val = get_value_smart(key, locale_data)
            if val is not None:
                return val, "smart_lookup"
            
    return None, None

def resolve_issue_candidate_value(issue: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """
    Extract the suggested/replacement value for an issue.
    Returns (value, source_of_determination).
    """
    details = issue.get("details", {}) or {}
    
    # 1. Explicit approved/suggested fields
    candidates = [
        ("approved_new", issue.get("approved_new")),
        ("candidate_value", issue.get("candidate_value")),
        ("suggested_fix", issue.get("suggested_fix")),
        ("details.new", details.get("new")),
        ("issue.new", issue.get("new")),
        ("suggestion", issue.get("suggestion")),
        ("details.candidate_value", details.get("candidate_value")),
        ("details.suggestion", details.get("suggestion")),
    ]
    
    for source_name, raw_val in candidates:
        # Handle LanguageTool 'replacements' array or list in raw_val
        if isinstance(raw_val, list):
            if len(raw_val) > 0:
                first = raw_val[0]
                val = None
                if isinstance(first, dict):
                    val = normalized_non_empty_string(first.get("value") or first.get("text"))
                else:
                    val = normalized_non_empty_string(first)
                
                if val is not None:
                    return val, f"{source_name}[0]"
            continue

        val = normalized_non_empty_string(raw_val)
        if val is not None:
            return val, source_name

    # 2. Handle LanguageTool 'replacements' array specifically if missed above
    replacements = details.get("replacements") or issue.get("replacements")
    if replacements:
        if isinstance(replacements, list) and len(replacements) > 0:
            first = replacements[0]
            val = None
            if isinstance(first, dict):
                val = normalized_non_empty_string(first.get("value") or first.get("text"))
            else:
                val = normalized_non_empty_string(first)
            
            if val is not None:
                return val, "replacements[0]"
        elif isinstance(replacements, str):
            val = normalized_non_empty_string(replacements)
            if val is not None:
                return val, "replacements_string"

    return None, None
