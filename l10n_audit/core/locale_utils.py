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

def resolve_canonical_locale_key(target_key: str, locale_data: Dict[str, Any]) -> tuple[Optional[str], str]:
    """
    Resolve a lookup key against canonical flattened locale data.

    Resolution is intentionally narrow:
    - exact canonical key match
    - unambiguous suffix match on dot-separated boundaries

    Ambiguous suffix matches are treated as unresolved.
    """
    if not target_key or not locale_data:
        return None, "unresolved"

    if target_key in locale_data:
        return target_key, "exact"

    search_suffix = f".{target_key}"
    matches = [key for key in locale_data if key.endswith(search_suffix)]
    if len(matches) == 1:
        return matches[0], "suffix"
    if len(matches) > 1:
        return None, "ambiguous_suffix"
    return None, "unresolved"


def resolve_locale_value(target_key: str, locale_data: Dict[str, Any]) -> dict[str, Optional[str]]:
    """
    Resolve a translation value while preserving lookup state.
    """
    resolved_key, resolution = resolve_canonical_locale_key(target_key, locale_data)
    if resolved_key is None:
        return {
            "value": None,
            "resolved_key": None,
            "status": resolution,
            "source": None,
        }

    raw_value = locale_data.get(resolved_key)
    if raw_value is None:
        return {
            "value": None,
            "resolved_key": resolved_key,
            "status": "resolved_null",
            "source": resolution,
        }

    value = str(raw_value)
    return {
        "value": value,
        "resolved_key": resolved_key,
        "status": "resolved_empty" if value == "" else "resolved",
        "source": resolution,
    }


def get_value_smart(target_key: str, locale_data: Dict[str, Any]) -> Optional[str]:
    """
    Perform a narrow lookup for a key in a potentially flattened locale mapping.
    Handles exact canonical match and unambiguous suffix matching for nested keys.
    """
    result = resolve_locale_value(target_key, locale_data)
    return result["value"]


def resolve_issue_current_value_state(
    issue: Dict[str, Any],
    locale_data: Optional[Dict[str, Any]] = None,
) -> dict[str, Optional[str]]:
    """
    Extract the original/source value for an issue while preserving resolution state.
    """
    details = issue.get("details", {}) or {}

    candidates = [
        ("source_old_value", issue.get("source_old_value")),
        ("current_value", issue.get("current_value")),
        ("target", issue.get("target")),
        ("details.old", details.get("old")),
        ("issue.old", issue.get("old")),
        ("current_translation", issue.get("current_translation")),
    ]

    for source_name, raw_val in candidates:
        if raw_val is None:
            continue
        if isinstance(raw_val, str):
            stripped = raw_val.strip()
            if stripped:
                return {"value": stripped, "source": source_name, "status": "resolved"}
            return {"value": "", "source": source_name, "status": "resolved_empty"}

        val = normalized_non_empty_string(raw_val)
        if val is not None:
            return {"value": val, "source": source_name, "status": "resolved"}

    if locale_data:
        key = normalized_non_empty_string(issue.get("key"))
        if key:
            lookup = resolve_locale_value(key, locale_data)
            if lookup["status"] in {"resolved", "resolved_empty"}:
                return {
                    "value": lookup["value"],
                    "source": "smart_lookup",
                    "status": lookup["status"],
                    "resolved_key": lookup["resolved_key"],
                    "lookup_source": lookup["source"],
                }
            return {
                "value": None,
                "source": "smart_lookup",
                "status": lookup["status"],
                "resolved_key": lookup["resolved_key"],
                "lookup_source": lookup["source"],
            }

    return {"value": None, "source": None, "status": "unresolved"}

def resolve_issue_current_value(issue: Dict[str, Any], locale_data: Optional[Dict[str, Any]] = None) -> tuple[Optional[str], Optional[str]]:
    """
    Extract the original/source value for an issue.
    Returns (value, source_of_determination).
    """
    result = resolve_issue_current_value_state(issue, locale_data=locale_data)
    return result.get("value"), result.get("source")

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
