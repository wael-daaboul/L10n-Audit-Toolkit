#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import uuid
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from l10n_audit.core.audit_report_utils import load_all_report_issues, severity_rank, summarize_issues, write_unified_json
from l10n_audit.core.artifact_resolver import resolve_master_path, resolve_final_report_path
from l10n_audit.core.audit_runtime import compute_plan_id, compute_text_hash, load_locale_mapping, load_runtime, write_simple_xlsx
from l10n_audit.fixes.apply_safe_fixes import build_fix_plan

REVIEW_QUEUE_COLUMNS = [
    "key",
    "locale",
    "old_value",
    "issue_type",
    "suggested_fix",
    "approved_new",
    "needs_review",
    "status",
    "notes",
    "context_type",
    "context_flags",
    "semantic_risk",
    "lt_signals",
    "review_reason",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
    "provenance",
]
HIDDEN_WHEN_EMPTY = {"placeholders", "icu_message_audit"}


def format_issue(issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity", "info")).upper()
    key = str(issue.get("key", ""))
    source = str(issue.get("source", ""))
    message = str(issue.get("message", ""))
    return f"- [{severity}] `{key}` ({source}) - {message}"


def safe_fix_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    plan = build_fix_plan(issues)
    return {
        "available": sum(1 for item in plan if item["classification"] == "auto_safe"),
        "review_required": sum(1 for item in plan if item["classification"] == "review_required"),
    }


def priority_order(issues: list[dict[str, Any]]) -> list[str]:
    grouped = Counter(str(issue.get("source", "")) for issue in issues if str(issue.get("severity", "")) in {"critical", "high"})
    if not grouped:
        grouped = Counter(str(issue.get("source", "")) for issue in issues)
    return [source for source, _count in grouped.most_common()]


def recommendations(summary: dict[str, Any], safe_fixes: dict[str, int], review_rows: list[dict[str, str]]) -> list[str]:
    items = []
    if summary["total_issues"]:
        items.append("Start with critical and high-severity issues shown in the dashboard before wording polish.")
    if safe_fixes["available"]:
        items.append("Run `./bin/run_all_audits.sh --stage autofix` to generate auto-safe locale candidates and the safe fix report.")
    if review_rows:
        items.append("Resolve pending items in `Results/review/review_queue.xlsx`, then apply approved rows with `python -m fixes.apply_review_fixes`.")
    return items or ["No action is required because no issues were found."]


def review_locale(issue: dict[str, Any]) -> str:
    locale = str(issue.get("locale", "")).strip()
    source = str(issue.get("source", ""))
    if locale in {"ar", "en"}:
        return locale
    if source in {"ar_locale_qc", "ar_semantic_qc", "terminology"}:
        return "ar"
    if source in {"locale_qc", "grammar"}:
        return "en"
    return locale or "ar"


_SOURCE_LOCALE_MAP: dict[str, str] = {
    "ar_locale_qc": "ar",
    "ar_semantic_qc": "ar",
    "en_locale_qc": "en",
    "en_grammar_audit": "en",
}


def _resolve_issue_locale(issue: dict) -> str:
    """Return the resolved locale for an issue, always one of 'ar', 'en', or 'unknown'.

    Resolution priority (strict):
      1. Explicit locale field
      2. Source-based inference via _SOURCE_LOCALE_MAP
      3. Key prefix inference  ('ar.' / 'en.' via split)
      4. File path inference   ('/ar/', 'ar.json', '/en/', 'en.json')
      5. Fallback → 'unknown'

    Never raises. Never returns an empty string.
    """
    # Input validation
    if not isinstance(issue, dict):
        return "unknown"

    # 1. Explicit locale — normalize to lowercase
    locale = str(issue.get("locale", "") or "").strip().lower()
    if locale in {"ar", "en"}:
        return locale

    # 2. Source-based inference — normalize to lowercase
    source = str(issue.get("source", "") or "").strip().lower()
    if source in _SOURCE_LOCALE_MAP:
        return _SOURCE_LOCALE_MAP[source]

    # 3. Key prefix inference via split to avoid false positives (e.g. "archive")
    key = str(issue.get("key", "") or "").strip()
    if key:
        first_segment = key.split(".")[0].lower()
        if first_segment == "ar":
            return "ar"
        if first_segment == "en":
            return "en"

    # 4. File path inference — normalize to lowercase, unify separators
    file_path = str(issue.get("file_path", "") or "").strip().lower().replace("\\", "/")
    if file_path:
        if "/ar/" in file_path or file_path.endswith("ar.json"):
            return "ar"
        if "/en/" in file_path or file_path.endswith("en.json"):
            return "en"

    # 5. Fallback
    return "unknown"

# ---------------------------------------------------------------------------
# Phase 7: Candidate Safety Gate (Proper Nouns & Brand Identity)
# ---------------------------------------------------------------------------

_PROTECTED_BRANDS = {
    "bkash", "paytm", "mercadopago", "flutterwave", "paytabs", "moonbid", "betaxi",
    "stripe", "paypal", "razorpay", "instamojo", "billplz"
}
_PROTECTED_ACRONYMS = {
    "API", "OTP", "VIN", "JSON", "ICU", "URL", "PIN", "CVV", "IBAN", "SWIFT", "VAT"
}
_CAMEL_CASE_RE = re.compile(r'[A-Z][a-z]+[A-Z]')

def _is_unsafe_mutation(cur: str, fix: str) -> bool:
    """Detect brand identity violations, token splitting, or proper noun substitution (Phase 7).
    
    This gate is strictly conservative: it only allows mechanical changes and blocks 
    any modification to identity-carrying tokens.
    """
    if not cur or not fix or cur == fix:
        return False
        
    # Unicode-aware word tokenization
    tokens_cur = re.findall(r'\w+', cur, re.UNICODE)
    tokens_fix = re.findall(r'\w+', fix, re.UNICODE)
    
    # 1. Token Identity Correlation check (Splitting/Joining)
    # If fix has different token count but matches normalized form -> splitting/joining error.
    if len(tokens_fix) != len(tokens_cur):
        if "".join(tokens_fix).lower() == "".join(tokens_cur).lower():
            return True

    # 2. Detailed Token-by-Token Safety Inspection
    for t in tokens_cur:
        # Identity Tokens: Brands, Acronyms, CamelCase, and Mixed-Script
        is_protected = t.lower() in _PROTECTED_BRANDS
        is_acronym = t.isupper() and len(t) >= 2 and t in _PROTECTED_ACRONYMS
        is_camel = bool(_CAMEL_CASE_RE.match(t))
        
        # Mixed-script branded tokens (e.g., Payتم or Bkash_خدمة)
        is_mixed = bool(re.search(r'[A-Za-z]', t)) and bool(re.search(r'[^\x00-\x7F]', t))
        
        if is_protected or is_acronym or is_camel or is_mixed:
            # Identity tokens must be perfectly preserved (case-sensitive).
            if t not in tokens_fix:
                return True
                    
    return False


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _is_low_risk_fix(cur: str, fix: str) -> bool:
    """Phase 8: Return True for mechanical or confirmed low-risk normalization."""
    if not cur or not fix:
        return False
    if cur == fix:
        return True
    
    # 1. Whitespace normalization (Curated Safe)
    cur_norm = re.sub(r'\s+', ' ', cur).strip()
    fix_norm = re.sub(r'\s+', ' ', fix).strip()
    if cur_norm == fix_norm:
        return True
        
    # 2. Case normalization (e.g. EMAIL -> Email)
    if cur.lower() == fix.lower():
        return True
        
    # 3. Punctuation normalization (e.g. Hello -> Hello.)
    # (Identity/Brands are protected by Phase 7 check BEFORE this helper is called)
    punc_pattern = r'[\s.,!?;:]+'
    cur_punc = re.sub(punc_pattern, '', cur).lower()
    fix_punc = re.sub(punc_pattern, '', fix).lower()
    if cur_punc == fix_punc:
        return True
        
    # 4. Low-risk typo correction (Minimal word-edit distance)
    # Check if we have the same number of word-tokens
    tokens_cur = re.findall(r'\w+', cur, re.UNICODE)
    tokens_fix = re.findall(r'\w+', fix, re.UNICODE)
    
    if len(tokens_cur) == len(tokens_fix) and len(tokens_cur) > 0:
        diff_indices = [i for i in range(len(tokens_cur)) if tokens_cur[i] != tokens_fix[i]]
        if len(diff_indices) == 1:
            idx = diff_indices[0]
            # Typo bucket: Distance <= 2 (e.g., mision -> mission)
            if _levenshtein_distance(tokens_cur[idx].lower(), tokens_fix[idx].lower()) <= 2:
                return True
                
    return False


def _resolve_candidate_value(
    issue: dict,
    current_value: str,
    suggested_fix: str,
) -> dict:
    """Pure decision helper: resolve the best candidate value for a single issue.

    Returns a dict with exactly 4 keys:
        candidate_value   str
        resolution_mode   str  one of: suggested_fix | current_value | no_candidate | conflict
        conflict_flag     str  one of: "" | IDENTICAL_TO_CURRENT | EMPTY_SUGGESTION | STRUCTURAL_RISK
        notes_token       str  one of: "" | [DQ:SAFE_AUTO_PROJECTED] | [KEEP:CURRENT_VALUE] | [NO_CANDIDATE] | [CONFLICT:STRUCTURAL_RISK]

    Decision order (strict):
      1. Empty suggestion       → no_candidate
      2. Identical to current   → current_value
      3. Structural risk        → conflict
      4. Safe                   → suggested_fix
    """
    # Guard: never raise regardless of input types
    try:
        fix = str(suggested_fix) if suggested_fix is not None else ""
        cur = str(current_value) if current_value is not None else ""
    except Exception:
        return {
            "candidate_value": "",
            "resolution_mode": "no_candidate",
            "conflict_flag": "EMPTY_SUGGESTION",
            "notes_token": "[NO_CANDIDATE]",
        }

    # 1. Empty suggestion
    if not fix.strip():
        return {
            "candidate_value": "",
            "resolution_mode": "no_candidate",
            "conflict_flag": "EMPTY_SUGGESTION",
            "notes_token": "[NO_CANDIDATE]",
        }

    # 2. Identical to current
    if fix.strip() == cur.strip():
        return {
            "candidate_value": cur,
            "resolution_mode": "current_value",
            "conflict_flag": "IDENTICAL_TO_CURRENT",
            "notes_token": "[KEEP:CURRENT_VALUE]",
        }

    # 3. Structural risk — deterministic token-count heuristic
    def _counts(s: str) -> tuple:
        return (
            s.count("{{"),
            s.count("}}"),
            s.count("<"),
            s.count(">"),
            s.count("\n"),
        )

    if _counts(fix) != _counts(cur):
        return {
            "candidate_value": "",
            "resolution_mode": "conflict",
            "conflict_flag": "STRUCTURAL_RISK",
            "notes_token": "[CONFLICT:STRUCTURAL_RISK]",
        }

    # 4. Phase 7: Safety Gate (Brand/Identity Protection)
    if _is_unsafe_mutation(cur, fix):
        return {
            "candidate_value": "",
            "resolution_mode": "conflict",
            "conflict_flag": "SAFETY_VETO",
            "notes_token": "[CONFLICT:SAFETY_VETO]",
        }

    # 5. Safe suggested fix
    return {
        "candidate_value": fix,
        "resolution_mode": "suggested_fix",
        "conflict_flag": "",
        "notes_token": "[DQ:SAFE_AUTO_PROJECTED]",
    }


_NEEDS_REVIEW_TRUTHY = {"true", "yes", "1"}
_HIGH_SEVERITY = {"high", "critical"}


def _project_approved_new(issue: dict, resolution: dict) -> str:
    """Pure projection helper: decide whether approved_new should be auto-filled.

    Returns the projected approved value string, or "" when human review is required.
    Never returns None. Never raises.

    Decision order (strict):
      1. No candidate (no_candidate / conflict)  → ""
      2. Explicit needs_review flag              → ""
      3. High/critical severity                  → ""
      4. High semantic_risk                      → ""
      5. Non-empty review_reason                 → ""
      6. Safe suggested_fix with non-empty value → candidate_value
      7. All other cases                         → ""
    """
    try:
        # 1. No candidate available
        mode = str(resolution.get("resolution_mode", "")).strip()
        if mode in ("no_candidate", "conflict"):
            return ""

        # 2. Explicit review required
        needs_review = issue.get("needs_review")
        if needs_review is True:
            return ""
        if isinstance(needs_review, str) and needs_review.strip().lower() in _NEEDS_REVIEW_TRUTHY:
            return ""

        # 3. High severity
        severity = str(issue.get("severity", "") or "").strip().lower()
        if severity in _HIGH_SEVERITY:
            return ""

        # 4. High semantic risk
        details = issue.get("details") or {}
        semantic_risk = str(details.get("semantic_risk", "") or "").strip().lower()
        if semantic_risk == "high":
            return ""

        # 5. Review reason exists
        review_reason = str(details.get("review_reason", "") or "").strip()
        if review_reason:
            return ""

        # 6. Suggested fix - Phase 8 Hardening: only auto-project low-risk fixes
        if mode == "suggested_fix":
            candidate = str(resolution.get("candidate_value", "") or "").strip()
            if candidate:
                # Robustly find the current value for comparison
                current = str(issue.get("current_value") or issue.get("old_value") or 
                             (issue.get("details", {}) or {}).get("old") or "")
                if _is_low_risk_fix(current, candidate):
                    return candidate

    except Exception:
        pass

    # 7. All other cases
    return ""


def old_value_for_issue(issue: dict[str, Any], en_data: dict[str, object], ar_data: dict[str, object]) -> str:
    details = issue.get("details", {})
    explicit = str(details.get("old", ""))
    if explicit:
        return explicit
    locale = _resolve_issue_locale(issue)
    key = str(issue.get("key", ""))
    if locale == "en":
        return str(en_data.get(key, ""))
    if locale == "ar":
        return str(ar_data.get(key, ""))
    return ""


def suggested_fix_for_issue(issue: dict[str, Any], en_data: dict[str, object], ar_data: dict[str, object]) -> str:
    # v1.3.1 - Prioritize top-level fields populated by AI review or merging
    for field in ("suggested_fix", "suggestion", "approved_new"):
        val = str(issue.get(field) or "")
        if val:
            return val

    details = issue.get("details", {})
    for field in ("new", "candidate_value", "expected_ar", "use_instead"):
        value = str(details.get(field, ""))
        if value:
            return value

    locale = _resolve_issue_locale(issue)
    issue_type = str(issue.get("issue_type", ""))
    key = str(issue.get("key", ""))
    if issue_type in {"confirmed_missing_key", "missing_in_ar", "in_en_not_ar"} and locale == "ar":
        return str(en_data.get(key, ""))
    if issue_type in {"missing_in_en", "in_ar_not_en"} and locale == "en":
        return str(ar_data.get(key, ""))
    return ""


def _normalize_review_row(row: dict) -> dict:
    """Phase 10: Tighten and stabilize review queue row semantics."""
    normalized = dict(row)
    for field in [
        "key", "locale", "old_value", "issue_type", "suggested_fix",
        "approved_new", "status", "notes", "provenance", "source_hash",
        "suggested_hash", "plan_id", "needs_review"
    ]:
        if field in normalized:
            val = normalized[field]
            normalized[field] = "" if val is None else str(val)

    # Normalize notes (Stable, unique segments)
    notes = normalized.get("notes", "")
    note_segments = [s.strip() for s in notes.split(" | ") if s.strip()]
    unique_notes = []
    seen = set()
    for s in note_segments:
        if s not in seen:
            unique_notes.append(s)
            seen.add(s)
    normalized["notes"] = " | ".join(unique_notes)

    # Normalize provenance (Stable, unique, sorted segments)
    prov = normalized.get("provenance", "")
    prov_segments = sorted(list(set(filter(None, prov.split(" || ")))))
    normalized["provenance"] = " || ".join(prov_segments)

    # Tighten needs_review logic (Semantic Hardening)
    # 1. If approved_new is empty, review is MANDATORY (Yes) because there is no safe target.
    # 2. If approved_new is populated, we preserve the existing 'Yes' (High severity) but don't force it.
    if not normalized.get("approved_new"):
        normalized["needs_review"] = "Yes"
    
    # Ensure suggested_fix is actionable only
    # If the suggestion is effectively a no-op, we clear it to avoid blind/noisy approvals.
    if normalized.get("suggested_fix") == normalized.get("old_value"):
        normalized["suggested_fix"] = ""
        normalized["suggested_hash"] = compute_text_hash("")

    return normalized


def _classify_decision_quality(
    issue: dict,
    resolution: dict,
    projected_approved_new: str,
) -> dict:
    try:
        res_mode = str(resolution.get("resolution_mode", "")).strip()
        
        # 1. Conflict
        if res_mode == "conflict":
            reason = "conflict"
            token = "[DQ:BLOCKED]"
            if str(resolution.get("conflict_flag", "")) == "SAFETY_VETO":
                reason = "safety_gate"
            
            return {
                "decision_quality": "blocked",
                "decision_reason": reason,
                "decision_token": token,
            }

        # 2. No candidate
        if res_mode == "no_candidate":
            return {
                "decision_quality": "blocked",
                "decision_reason": "no_candidate",
                "decision_token": "[DQ:BLOCKED]",
            }

        # 3. Explicit review required
        needs_review = issue.get("needs_review")
        if needs_review is True:
            return {
                "decision_quality": "review_required",
                "decision_reason": "needs_review",
                "decision_token": "[DQ:REVIEW_REQUIRED]",
            }
        if isinstance(needs_review, str) and needs_review.strip().lower() in {"true", "yes", "1"}:
            return {
                "decision_quality": "review_required",
                "decision_reason": "needs_review",
                "decision_token": "[DQ:REVIEW_REQUIRED]",
            }

        # 4. High severity
        severity = str(issue.get("severity", "") or "").strip().lower()
        if severity in {"high", "critical"}:
            return {
                "decision_quality": "review_required",
                "decision_reason": "high_severity",
                "decision_token": "[DQ:REVIEW_REQUIRED]",
            }

        details = issue.get("details", {}) or {}

        # 5. High semantic risk
        semantic_risk = str(details.get("semantic_risk", "") or "").strip().lower()
        if semantic_risk == "high":
            return {
                "decision_quality": "review_required",
                "decision_reason": "high_semantic_risk",
                "decision_token": "[DQ:REVIEW_REQUIRED]",
            }

        # 6. Review reason present
        review_reason = str(details.get("review_reason", "") or "").strip()
        if review_reason:
            return {
                "decision_quality": "review_required",
                "decision_reason": "review_reason_present",
                "decision_token": "[DQ:REVIEW_REQUIRED]",
            }

        # 7. Safe auto projected
        if projected_approved_new:
            return {
                "decision_quality": "safe_auto_projected",
                "decision_reason": "safe_mechanical_normalization",
                "decision_token": "[DQ:SAFE_AUTO_PROJECTED]",
            }

        return {
            "decision_quality": "suggestion_only",
            "decision_reason": "not_approved_semantic_or_complex",
            "decision_token": "[DQ:SUGGESTION_ONLY]",
        }

    except Exception:
        pass

    # 9. Fallback
    return {
        "decision_quality": "review_required",
        "decision_reason": "fallback",
        "decision_token": "[DQ:REVIEW_REQUIRED]",
    }


def build_review_queue(issues: list[dict[str, Any]], runtime) -> list[dict[str, str]]:
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    ar_data = load_locale_mapping(runtime.ar_file, runtime, target_locale)
    auto_safe = {
        (
            str(item["key"]),
            str(item["locale"]),
            str(item["issue_type"]),
            str(item["candidate_value"]),
        )
        for item in build_fix_plan(issues)
        if item["classification"] == "auto_safe"
    }

    rows_by_key: dict[tuple[str, str], dict[str, str]] = {}
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    
    for issue in issues:
        if str(issue.get("severity", "")).lower() == "info":
            continue
            
        locale = _resolve_issue_locale(issue)
        key = str(issue.get("key", ""))
        issue_type = str(issue.get("issue_type", ""))
        current_value = old_value_for_issue(issue, en_data, ar_data)
        suggested_fix = suggested_fix_for_issue(issue, en_data, ar_data)
        message = str(issue.get("message", ""))
        source = str(issue.get("source", ""))
        severity = str(issue.get("severity", ""))
        resolution = _resolve_candidate_value(issue, current_value, suggested_fix)
        resolved_fix = resolution["candidate_value"]
        notes_token = resolution["notes_token"]
        projected_approved_new = _project_approved_new(issue, resolution)
        decision = _classify_decision_quality(issue, resolution, projected_approved_new)
        decision_token = decision["decision_token"]

        row_key = (key, locale)
        if row_key in rows_by_key:
            existing = rows_by_key[row_key]
            # Merge unique issue types
            if issue_type not in existing["issue_type"].split(" | "):
                existing["issue_type"] += f" | {issue_type}"
            # Merge unique notes
            if message not in existing["notes"].split(" | "):
                existing["notes"] += f" | {message}"
            # Append notes_token if not already present
            if notes_token and notes_token not in existing["notes"].split(" | "):
                existing["notes"] += f" | {notes_token}"
            # Append decision_token if not already present
            if decision_token and decision_token not in existing["notes"].split(" | "):
                existing["notes"] += f" | {decision_token}"
            # Merge provenance
            prov_segment = f"{source}|{issue_type}|{severity}"
            if prov_segment not in existing["provenance"].split(" || "):
                existing["provenance"] += f" || {prov_segment}"
            # Force clear when resolution signals conflict or no candidate
            resolution_mode = resolution["resolution_mode"]
            if resolution_mode in ("conflict", "no_candidate"):
                existing["suggested_fix"] = ""
                existing["suggested_hash"] = compute_text_hash("")
            else:
                # Prioritize AI suggestions if they exist
                is_ai = source in ("ai_review", "ai_suggestion") or "ai_suggestion" in issue_type
                if is_ai and resolved_fix:
                    existing["suggested_fix"] = resolved_fix
                    existing["suggested_hash"] = compute_text_hash(resolved_fix)
                    if "|ai_reviewed" not in existing["provenance"]:
                        existing["provenance"] += "|ai_reviewed"
                elif not existing["suggested_fix"] and resolved_fix:
                    existing["suggested_fix"] = resolved_fix
                    existing["suggested_hash"] = compute_text_hash(resolved_fix)
            # Project approved_new if not already set
            if not existing["approved_new"] and projected_approved_new:
                existing["approved_new"] = projected_approved_new
            rows_by_key[row_key] = _normalize_review_row(existing)
        else:
            resolved_notes = " | ".join(filter(None, [message, notes_token, decision_token]))
            new_row = {
                "key": key,
                "locale": locale,
                "old_value": current_value,
                "issue_type": issue_type,
                "suggested_fix": resolved_fix,
                "approved_new": projected_approved_new,
                "needs_review": "Yes" if issue.get("needs_review") or issue.get("severity") in ("critical", "high") else "No",
                "status": "pending",
                "notes": resolved_notes,
                "context_type": str((issue.get("details", {}) or {}).get("context_type", "")),
                "context_flags": str((issue.get("details", {}) or {}).get("context_flags", "")),
                "semantic_risk": str((issue.get("details", {}) or {}).get("semantic_risk", "")),
                "lt_signals": str((issue.get("details", {}) or {}).get("lt_signals", "")),
                "review_reason": str((issue.get("details", {}) or {}).get("review_reason", "")),
                "source_old_value": current_value,
                "source_hash": compute_text_hash(current_value),
                "suggested_hash": compute_text_hash(resolved_fix),
                "plan_id": compute_plan_id(key, locale, issue_type, current_value, suggested_fix),
                "generated_at": generated_at,
                "provenance": f"{source}|{issue_type}|{severity}",
                "_severity": str(issue.get("severity", "info")).lower(),
                "_source": str(issue.get("source", "unknown")),
            }
            rows_by_key[row_key] = _normalize_review_row(new_row)

    rows = list(rows_by_key.values())
    
    # Phase 9: No-Op / Noise Suppression
    meaningful_rows = []
    for row in rows:
        notes = row.get("notes", "")
        fix = row.get("suggested_fix", "")
        old = row.get("old_value", "")
        
        # 1. Actionable Suggestion (different from current)
        has_new_suggestion = fix and (fix != old)
        
        # 2. Meaningful Block/Conflict (needs manual review)
        # Includes IDENTITY_VETO, STRUCTURAL_RISK, SAFETY_VETO, etc.
        is_review_worthy_block = "[CONFLICT:" in notes or "safety_gate" in notes
        
        # Suppression: Exclude empty/no-candidate noise and keep-current rows
        if has_new_suggestion or is_review_worthy_block:
            meaningful_rows.append(row)
            
    rows = meaningful_rows
    rows.sort(key=lambda row: (row["locale"], row["key"], row["issue_type"]))
    return rows


def build_source_status(reports: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, str]:
    counts = Counter(str(issue["source"]) for issue in issues)
    status: dict[str, str] = {}
    for source in sorted(reports):
        if source in HIDDEN_WHEN_EMPTY and counts.get(source, 0) == 0:
            status[source] = "passed"
        else:
            status[source] = f"{counts.get(source, 0)} issues"
    return status


def render_markdown(
    issues: list[dict[str, Any]],
    summary: dict[str, Any],
    safe_fixes: dict[str, int],
    review_rows: list[dict[str, str]],
    source_status: dict[str, str],
    missing: list[str],
) -> str:
    critical_count = sum(1 for issue in issues if str(issue.get("severity")) in {"critical", "high"})
    actionable = [
        issue for issue in issues 
        if (str(issue.get("source")) not in HIDDEN_WHEN_EMPTY or source_status.get(str(issue.get("source"))) != "passed")
        and str(issue.get("severity", "")).lower() != "info"
    ]
    top_review = sorted(
        actionable,
        key=lambda issue: (
            severity_rank(str(issue.get("severity", "info"))),
            str(issue.get("source", "")),
            str(issue.get("key", "")),
        ),
    )

    lines = [
        "# Final Localization Audit Report",
        "",
        "Workflow: Run Audit -> Open Dashboard -> Review Queue -> Apply Safe Fixes -> Export Final Locale",
        "",
        "## Summary",
        "",
        f"- total issues: **{summary['total_issues']}**",
        f"- critical issues: **{critical_count}**",
        f"- safe fixes available: **{safe_fixes['available']}**",
        f"- review required issues: **{len(review_rows)}**",
        "",
        "## Main Outputs",
        "",
        "- dashboard: `Results/final/final_audit_report.md`",
        "- review queue: `Results/review/review_queue.xlsx`",
        "- final locale: `Results/final_locale/ar.final.json`",
        "",
        "## Review Queue",
        "",
        "Open `Results/review/review_queue.xlsx`, update `approved_new`, then set `status` to `approved` for rows you want to apply.",
        "",
        "## Prioritized Review",
        "",
    ]

    if top_review:
        for issue in top_review[:30]:
            lines.append(format_issue(issue))
    else:
        lines.append("- No actionable issues.")
    lines.append("")

    lines.append("## Audit Status")
    lines.append("")
    for source, status in source_status.items():
        lines.append(f"- {source}: **{status}**")
    lines.append("")

    if missing:
        lines.append("## Missing Reports")
        lines.append("")
        for item in missing:
            lines.append(f"- `{item}`")
        lines.append("")

    return "\n".join(lines)


def create_analytical_payload(
    review_rows: list[dict],
    issues: list[dict],
    reports: dict,
    missing: list,
    summary: dict,
    safe_fixes: dict,
    source_status: dict
) -> dict:
    """Phase 11: Construct a strictly reconciled analytical payload from filtered operational rows."""
    from collections import Counter
    
    # Deriving reconciled analytical summary from operational truth
    actionable_summary = {
        "total_issues": len(review_rows),
        "critical_issues": sum(1 for r in review_rows if r.get("_severity") in {"critical", "high"}),
        "safe_fixes_available": sum(1 for r in review_rows if r.get("needs_review") == "No"),
        "review_required_issues": sum(1 for r in review_rows if r.get("needs_review") == "Yes"),
        "blocked_issues": sum(1 for r in review_rows if "[DQ:BLOCKED]" in r.get("notes", "")),
        "by_severity": dict(sorted(Counter(r.get("_severity", "info") for r in review_rows).items())),
        "by_source": dict(sorted(Counter(r.get("_source", "unknown") for r in review_rows).items())),
        "by_issue_type": dict(sorted(Counter(r.get("issue_type", "unknown") for r in review_rows).items())),
    }

    include_sources = sorted(reports.keys())
    return {
        "summary": actionable_summary,
        "missing_reports": missing,
        "included_sources": include_sources,
        "priority_order": priority_order(issues),
        "recommendations": recommendations(summary, safe_fixes, review_rows),
        "source_status": source_status,
        "review_queue": review_rows,
        "issues": issues,
    }


def _build_deprecation_governance() -> dict:
    """Return a JSON-safe summary of the Phase E deprecation registry.

    Imported lazily so that cyclic-import risk is minimised and the registry
    module can remain a pure-data file with no runtime side effects.
    """
    try:
        from l10n_audit.core.deprecation_registry import summary_dict
        from l10n_audit.core.deprecation_warnings import get_usage_tracking
        sd = summary_dict()
        sd["usage_tracking"] = get_usage_tracking()
        return sd
    except Exception:
        return {"schema_version": "unavailable", "error": "deprecation_registry import failed"}


def write_audit_master(
    artifacts_dir: Path,
    aggr_file: Path,
    json_file: Path,
    review_json: Path,
    review_xlsx: Path,
    issues: list,
    review_rows: list,
    payload: dict,
    missing: list,
    include_sources: list,
    source_status: dict,
    project_root: Path,
    # Phase A optional enrichment args (callers need not pass these)
    runtime=None,
    options=None,
) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    master_file = artifacts_dir / "audit_master.json"

    def _rel(p: Path) -> str:
        try:
            return str(p.resolve().relative_to(project_root.resolve()))
        except ValueError:
            return str(p)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    summary = payload.get("summary", {})

    # ── Phase A: enriched run_metadata ─────────────────────────────────────
    def _safe_get(obj, *attrs, default=None):
        """Walk a chain of attribute/dict lookups without crashing."""
        cur = obj
        for a in attrs:
            if cur is None:
                return default
            try:
                cur = getattr(cur, a) if not isinstance(cur, dict) else cur.get(a)
            except Exception:
                return default
        return cur if cur is not None else default

    run_meta = {
        "generated_at": now_iso,
        "run_id": str(uuid.uuid4()),
        "pipeline_stage": "master_data_architecture",
        "tool_version": None,
        "input_mode": "master_hydrated" if (_safe_get(options, "input_report") is None) else "input_report",
        "source_locale": _safe_get(runtime, "source_locale"),
        "target_locales": list(_safe_get(runtime, "target_locales") or []),
        "locale_format": _safe_get(runtime, "locale_format"),
        "retention_mode": _safe_get(options, "retention_mode"),
        "project_root": str(project_root) if project_root else None,
        "results_dir": _rel(artifacts_dir.parent) if artifacts_dir else None,
    }

    # ── Phase A: summaries ──────────────────────────────────────────────────
    from collections import Counter as _Counter
    by_sev = dict(sorted(_Counter(str(i.get("severity","")) for i in issues).items())) if issues else {}
    by_src = dict(sorted(_Counter(str(i.get("source",""))   for i in issues).items())) if issues else {}
    by_typ = dict(sorted(_Counter(str(i.get("issue_type","")) for i in issues).items())) if issues else {}
    # workflow summary — counts from review_rows
    wf_total   = len(review_rows)
    wf_approved= sum(1 for r in review_rows if str(r.get("status","")).strip().lower() == "approved")
    wf_pending = sum(1 for r in review_rows if str(r.get("status","")).strip().lower() == "pending")
    summaries_section = {
        "issues": {
            "total_issues":    len(issues),
            "by_severity":     by_sev,
            "by_source":       by_src,
            "by_issue_type":   by_typ,
        },
        "workflow": {
            "total_review_rows": wf_total,
            "approved_rows":     wf_approved,
            "pending_rows":      wf_pending,
            # applied/not_approved resolved from workflow_state if it already exists
            "applied_rows":     None,
            "not_approved_rows": None,
        },
    }

    # ── Phase A: review_projection_metadata ────────────────────────────────
    rp_meta = {
        "review_queue_columns":     list(REVIEW_QUEUE_COLUMNS),
        "projection_generated_at": now_iso,
        "projection_source":       "legacy_generated",
        "projection_mode":         "build_review_queue",
    }

    # ── Phase A: apply_history (empty; entries appended by reconcile_master) 
    apply_history: list = []

    # ── Phase A: artifacts registry ────────────────────────────────────────
    results_dir = artifacts_dir.parent
    fix_plan = results_dir / ".cache" / "apply" / "fix_plan.json"
    if not fix_plan.exists():
        fix_plan = results_dir / "fixes" / "fix_plan.json"

    raw_reports_root = results_dir / ".cache" / "raw_tools"
    if not raw_reports_root.exists():
        raw_reports_root = results_dir / "per_tool"

    artifacts_reg = {
        "master_path":               _rel(master_file),
        "final_report_json_path":    _rel(json_file),
        "review_queue_json_path":    _rel(review_json),
        "review_queue_xlsx_path":    _rel(review_xlsx),
        "aggregated_issues_path":    _rel(aggr_file),
        "final_report_md_path":      _rel(results_dir / "final" / "final_audit_report.md"),
        "final_report_en_md_path":   _rel(results_dir / "final" / "final_audit_report_en.md"),
        "final_report_ar_md_path":   _rel(results_dir / "final" / "final_audit_report_ar.md"),
        "raw_reports_root":          _rel(raw_reports_root),
        "fix_plan_path":             _rel(fix_plan) if fix_plan.exists() else None,
    }

    # ── Compose full master payload (preserving all Phase 1-4 keys exactly) 
    master_payload = {
        # ── Existing keys (Phase 1) ── preserved exactly
        "run_metadata": run_meta,
        "sources": {
            "aggregated_issues_path": _rel(aggr_file),
            "final_audit_report_path": _rel(json_file),
            "review_queue_json_path": _rel(review_json),
            "review_queue_xlsx_path": _rel(review_xlsx)
        },
        "issue_inventory": issues,
        "review_projection": {
            "json_columns": list(REVIEW_QUEUE_COLUMNS),
            "json_rows": review_rows,
            "xlsx_columns_detected": list(REVIEW_QUEUE_COLUMNS)
        },
        "legacy_artifacts": {
            "final_report_snapshot": {
                "summary": summary,
                "missing_reports": missing,
                "included_sources": payload.get("included_sources", []) or include_sources,
                "priority_order": payload.get("priority_order", []),
                "recommendations": payload.get("recommendations", []),
                "source_status": source_status,
                "review_queue": review_rows
            }
        },
        # ── Phase 3 key ── reconcile_master overwrites this after apply
        "workflow_state": {},
        # ── Phase A new sections ──────────────────────────────────────────
        "summaries": summaries_section,
        "review_projection_metadata": rp_meta,
        "apply_history": apply_history,
        "artifacts": artifacts_reg,
        # ── Phase E: deprecation governance snapshot ────────────────────
        "deprecation_governance": _build_deprecation_governance(),
    }
    write_unified_json(master_file, master_payload)
    return master_file


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-en", default=str(runtime.results_dir / "final" / "final_audit_report_en.md"))
    parser.add_argument("--out-ar", default=str(runtime.results_dir / "final" / "final_audit_report_ar.md"))
    parser.add_argument("--out-md", default=str(runtime.results_dir / "final" / "final_audit_report.md"))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "final" / "final_audit_report.json"))
    parser.add_argument("--out-normalized", default=str(runtime.results_dir / "normalized" / "aggregated_issues.json"))
    parser.add_argument("--out-review-xlsx", default=str(runtime.results_dir / "review" / "review_queue.xlsx"))
    parser.add_argument("--out-review-json", default=str(runtime.results_dir / "review" / "review_queue.json"))
    parser.add_argument("--sources", default="")
    args = parser.parse_args()

    include_sources = {item.strip() for item in args.sources.split(",") if item.strip()} or None
    reports, issues, missing = load_all_report_issues(runtime.results_dir, include_sources=include_sources)
    summary = summarize_issues(issues)
    safe_fixes = safe_fix_counts(issues)
    review_rows = build_review_queue(issues, runtime)
    source_status = build_source_status(reports, issues)
    markdown = render_markdown(issues, summary, safe_fixes, review_rows, source_status, missing)

    payload = {
        "summary": {
            **summary,
            "critical_issues": sum(1 for issue in issues if str(issue.get("severity")) in {"critical", "high"}),
            "safe_fixes_available": safe_fixes["available"],
            "review_required_issues": len(review_rows),
        },
        "missing_reports": missing,
        "included_sources": sorted(include_sources) if include_sources else sorted(reports.keys()),
        "priority_order": priority_order(issues),
        "recommendations": recommendations(summary, safe_fixes, review_rows),
        "artifacts": {
            "dashboard": "Results/final/final_audit_report.md",
            "review_queue": "Results/review/review_queue.xlsx",
            "final_locale": "Results/final_locale/ar.final.json",
        },
        "workflow": [
            "Run Audit",
            "Open Dashboard",
            "Review Queue",
            "Apply Safe Fixes",
            "Export Final Locale",
        ],
        "source_status": source_status,
        "review_queue": review_rows,
        "issues": issues,
    }

    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_en).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_ar).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(markdown, encoding="utf-8")
    Path(args.out_en).write_text(markdown, encoding="utf-8")
    Path(args.out_ar).write_text(markdown, encoding="utf-8")
    write_unified_json(Path(args.out_json), payload)
    write_unified_json(Path(args.out_normalized), {"included_sources": payload["included_sources"], "issues": issues})
    write_unified_json(Path(args.out_review_json), {"columns": REVIEW_QUEUE_COLUMNS, "rows": review_rows})
    write_simple_xlsx(review_rows, REVIEW_QUEUE_COLUMNS, Path(args.out_review_xlsx), sheet_name="Review Queue")

    try:
        write_audit_master(
            artifacts_dir=runtime.results_dir / "artifacts",
            aggr_file=Path(args.out_normalized),
            json_file=Path(args.out_json),
            review_json=Path(args.out_review_json),
            review_xlsx=Path(args.out_review_xlsx),
            issues=issues,
            review_rows=review_rows,
            payload=payload,
            missing=missing,
            include_sources=sorted(include_sources) if include_sources else sorted(reports.keys()),
            source_status=source_status,
            project_root=runtime.project_root
        )
    except Exception as exc:
        print(f"Failed to write audit_master.json: {exc}")

    print(f"Done. Aggregated issues: {len(issues)}")
    print(f"Dashboard:   {args.out_md}")
    print(f"Review XLSX: {args.out_review_xlsx}")
    print(f"Review JSON: {args.out_review_json}")
    print(f"JSON:        {args.out_json}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def merge_issues_in_memory(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups issues by (key, locale) and merges AI suggestions into base issues.
    
    This handles the case where multiple tools (and AI) report on the same key.
    We prioritize 'empty_string', 'missing_in_ar', 'empty_ar' as base issues.
    """
    import logging
    logger = logging.getLogger("l10n_audit.merge")
    
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    
    for issue in issues:
        key = str(issue.get("key", ""))
        # Normalize locale: if empty or missing, assume 'ar' if it looks like an Arabic-related issue
        loc = str(issue.get("locale", "")).strip()
        source = str(issue.get("source", ""))
        it = str(issue.get("issue_type", ""))
        
        if not loc:
            if source in ("ar_locale_qc", "ar_semantic_qc", "ai_review") or "ar" in it or "arabic" in it.lower():
                loc = "ar"
            else:
                loc = "en" # Fallback
        
        groups.setdefault((key, loc), []).append(issue)
    
    merged: list[dict[str, Any]] = []
    
    for (key, loc), group_issues in groups.items():
        if len(group_issues) == 1:
            merged.append(group_issues[0])
            continue
            
        # 1. Identify Base Issue (Priority: empty_string > missing_in_ar > empty_ar > other)
        base_priority = ["empty_string", "missing_in_ar", "empty_ar", "missing_ar"]
        base_issue = None
        for bp in base_priority:
            for gi in group_issues:
                if str(gi.get("issue_type", "")) == bp:
                    base_issue = gi
                    break
            if base_issue: break
            
        if not base_issue:
            base_issue = group_issues[0] # Just take first as anchor
            
        # 2. Look for AI suggestions
        ai_item = None
        for gi in group_issues:
            if gi is base_issue: continue
            if str(gi.get("source", "")) in ("ai_review", "ai_suggestion") or "ai_suggestion" in str(gi.get("issue_type", "")):
                ai_item = gi
                break
        
        # 3. Perform Merge
        notes = [str(base_issue.get("message", ""))]
        provenance = [f"{base_issue.get('source')}|{base_issue.get('issue_type')}"]
        
        for gi in group_issues:
            if gi is base_issue: continue
            
            # Merge messages/notes if different
            msg = str(gi.get("message", ""))
            if msg and msg not in notes:
                notes.append(msg)
            
            # Merge provenance
            prov = f"{gi.get('source')}|{gi.get('issue_type')}"
            if prov not in provenance:
                provenance.append(prov)
                
        # Update base issue with AI suggestion and hashes
        if ai_item:
            # v1.3.1 - Robust extraction from multiple fields
            sugg = (
                str(ai_item.get("suggestion") or "") or
                str(ai_item.get("candidate_value") or "") or
                str(ai_item.get("approved_new") or "") or
                str(ai_item.get("suggested_fix") or "")
            ).strip()

            if sugg:
                base_issue["suggestion"] = sugg
                base_issue["suggested_fix"] = sugg
                base_issue["approved_new"] = sugg # Critical for direct application
                
                logger.info("Extracted translation from '%s' field for key '%s'", 
                    "suggestion" if ai_item.get("suggestion") else "other", key)
                
                # Critical for apply-review: Use Hashes from AI item
                if ai_item.get("source_hash"):
                    base_issue["source_hash"] = ai_item["source_hash"]
                if ai_item.get("suggested_hash"):
                    base_issue["suggested_hash"] = ai_item["suggested_hash"]
                
                logger.info("Applied AI suggestion to '%s' for key '%s'.", base_issue.get("issue_type"), key)
                if "ai_merged" not in str(base_issue.get("provenance", "")):
                    base_issue["provenance"] = (base_issue.get("provenance", "") + "|ai_merged").strip("|")

        base_issue["message"] = " | ".join(filter(None, notes))
        # Keep track of original sources in extra for debugging
        base_issue.setdefault("extra", {})["original_sources"] = provenance
        
        logger.info("Merged %d issues for key '%s' into 1. (Hashes copied: %s)", 
                    len(group_issues), key, "Yes" if ai_item and ai_item.get("suggested_hash") else "No")
        merged.append(base_issue)
        
    return merged


def _row_identity(row: dict) -> str:
    """Stable identity for a review row — mirrors Phase 3 _stable_identity.

    Primary key: ``plan_id`` (UUID written by build_review_queue).
    Fallback: composite ``key|locale|source_hash`` when plan_id absent.

    Must stay in sync with  apply_review_fixes._stable_identity.
    """
    pid = str(row.get("plan_id", "")).strip()
    if pid:
        return pid
    return "|".join([
        str(row.get("key", "")),
        str(row.get("locale", "")),
        str(row.get("source_hash", "")),
    ])


def apply_workflow_state_to_rows(review_rows: list[dict], workflow_state: dict) -> list[dict]:
    """Overlay reconciled fields from workflow_state onto review rows.

    For every row whose identity matches a workflow_state entry, merge in:
    - ``approved_new``  (reflects the value that was approved/applied)
    - ``status``        (reflects latest reconciled state)

    Constraints:
    - Returns a NEW list of dicts; originals are not mutated.
    - Only the two fields above are merged; all other fields are preserved.
    - Rows without a matching workflow_state entry are left exactly as-is.
    - If workflow_state is empty or None, returns rows unchanged.
    """
    if not workflow_state:
        return review_rows

    result: list[dict] = []
    for row in review_rows:
        identity = _row_identity(row)
        ws_entry = workflow_state.get(identity)
        if ws_entry is None:
            result.append(row)
            continue
        # Shallow-copy the row so we don't mutate the source list
        merged = dict(row)
        
        # Phase 12 Stale Defense: Check if current source text matches reconciled history
        # (Exclude empty hashes from comparison to avoid false staleness on initial run)
        ws_source_hash = str(ws_entry.get("source_hash", "")).strip()
        current_source_hash = str(row.get("source_hash", "")).strip()
        
        is_stale = ws_source_hash and current_source_hash and (ws_source_hash != current_source_hash)
        
        if is_stale:
            # Source text changed: previous approval is unsafe
            merged["status"] = "stale"
            merged["notes"] = f"{merged.get('notes', '')} | [DQ:STALE_DECISION]".strip(" | ")
            merged["needs_review"] = "Yes"
        else:
            # Identity and source match: re-apply decisions
            reconciled_approved = str(ws_entry.get("approved_new", "")).strip()
            if reconciled_approved:
                merged["approved_new"] = reconciled_approved
            
            reconciled_status = str(ws_entry.get("status", "")).strip()
            if reconciled_status:
                merged["status"] = reconciled_status
                
        result.append(merged)
    return result


def load_from_master(master_path: Path) -> tuple[dict, list, list, list]:
    """Extract (reports_stub, issues, review_rows, missing) from audit_master.json.

    Returns a 4-tuple compatible with the load_hydrated_report signature so it
    can be used as a drop-in hydration source without touching downstream logic.
    """
    import json as _json
    with open(master_path, encoding="utf-8") as fh:
        master = _json.load(fh)

    issues: list[dict] = master.get("issue_inventory", [])
    review_rows: list[dict] = master.get("review_projection", {}).get("json_rows", [])
    snapshot = master.get("legacy_artifacts", {}).get("final_report_snapshot", {})
    missing: list = snapshot.get("missing_reports", [])
    included = snapshot.get("included_sources", [])
    # Build a minimal reports stub keyed by source name so the rest of the
    # pipeline can compute source_status without re-scanning disk.
    reports_stub: dict = {src: [] for src in included}
    return reports_stub, issues, review_rows, missing


def run_stage(runtime, options, **kwargs) -> list[ReportArtifact]:
    """Aggregate per-tool reports and write the final dashboard and review queue.

    This calls the same logic as :func:`main` but without argparse.
    Returns a list of :class:`~l10n_audit.models.ReportArtifact` for the
    generated files.
    """
    import logging
    from l10n_audit.models import ReportArtifact
    from l10n_audit.core.deprecation_warnings import warn_deprecated_artifact
    from l10n_audit.core.audit_report_utils import load_all_report_issues, load_hydrated_report  # type: ignore[import]

    logger = logging.getLogger("l10n_audit.report_aggregator")
    results_dir = options.effective_output_dir(runtime.results_dir)
    include_sources = kwargs.get("sources")
    if isinstance(include_sources, str):
        include_sources = {s.strip() for s in include_sources.split(",") if s.strip()}

    artifacts: list[ReportArtifact] = []

    try:
        issues: list = []
        reports: dict = {}
        missing: list = []
        _master_hydrated_review_rows: list | None = None  # Phase 2: preserved from master

        # 1. Direct Hydration (User provided --input-report)
        if options.input_report:
            report_path = Path(options.input_report)
            logger.info("Hydrating from user-provided report: %s", report_path)
            reports, issues, missing = load_hydrated_report(report_path)

        # 1.5. Phase 2 — Hydrate from audit_master.json when available and no explicit report given
        if not issues:
            master_candidate = resolve_master_path(runtime)  # Phase B
            if master_candidate.exists():
                logger.info("Phase 2: Hydrating from audit_master.json: %s", master_candidate)
                try:
                    reports, issues, _master_hydrated_review_rows, missing = load_from_master(master_candidate)
                except Exception as master_exc:
                    logger.warning("Phase 2: Failed to load audit_master.json, falling back: %s", master_exc)
                    issues = []
                    reports = {}
                    missing = []
                    _master_hydrated_review_rows = None

        # 2. Per-tool scanning (Default behavior)
        if not issues:
            reports, issues, missing = load_all_report_issues(results_dir, include_sources=include_sources, options=options)

        # 3. Last-resort fallback to standard aggregate
        if not issues:
            std_agg = resolve_final_report_path(runtime)  # Phase B
            if std_agg.exists():
                logger.info("Falling back to standard aggregate report: %s", std_agg)
                reports, issues, missing = load_hydrated_report(std_agg)

        # v1.3.1 - In-Memory Merging & AI Alignment
        issues = merge_issues_in_memory(issues)

        summary = summarize_issues(issues)
        safe_fixes = safe_fix_counts(issues)
        # Phase 2: prefer review_rows from master projection to preserve any
        # human edits captured in a prior XLSX round-trip, falling back to
        # freshly computed rows when master hydration was not used.
        if _master_hydrated_review_rows is not None:
            review_rows = _master_hydrated_review_rows
            logger.info("Phase 2: Using %d review rows from audit_master projection.", len(review_rows))
        else:
            review_rows = build_review_queue(issues, runtime)
        source_status = build_source_status(reports, issues)

        # Phase 4 — Reproject review rows from reconciled workflow_state
        # Applied before render_markdown and payload construction so all
        # downstream outputs (JSON, XLSX, Markdown) reflect reconciled state.
        # Guarded: any failure leaves review_rows unchanged.
        try:
            master_candidate = resolve_master_path(runtime)  # Phase B
            if master_candidate.exists():
                import json as _mj
                _wf_master = _mj.loads(master_candidate.read_text(encoding="utf-8"))
                _workflow_state = _wf_master.get("workflow_state", {})
                if _workflow_state:
                    _reprojected = apply_workflow_state_to_rows(review_rows, _workflow_state)
                    _changed = sum(
                        1 for o, n in zip(review_rows, _reprojected)
                        if o.get("approved_new") != n.get("approved_new")
                        or o.get("status") != n.get("status")
                    )
                    review_rows = _reprojected
                    logger.info(
                        "Phase 4: Reprojected %d review rows (%d updated from workflow_state).",
                        len(review_rows), _changed,
                    )
        except Exception as _reproject_exc:
            logger.warning("Phase 4: Reprojection from workflow_state failed, using unchanged rows: %s", _reproject_exc)
        markdown = render_markdown(issues, summary, safe_fixes, review_rows, source_status, missing)

        payload = create_analytical_payload(
            review_rows=review_rows,
            issues=issues,
            reports=reports,
            missing=missing,
            summary=summary,
            safe_fixes=safe_fixes,
            source_status=source_status
        )

        final_dir = results_dir / "final"
        review_dir = results_dir / "review"
        normalized_dir = results_dir / "normalized"

        final_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        normalized_dir.mkdir(parents=True, exist_ok=True)

        # Write files
        md_file = final_dir / "final_audit_report.md"
        json_file = final_dir / "final_audit_report.json"
        aggr_file = normalized_dir / "aggregated_issues.json"
        review_json = review_dir / "review_queue.json"
        review_xlsx = review_dir / "review_queue.xlsx"

        md_file.write_text(markdown, encoding="utf-8")
        logger.debug("Phase G2/G3: Multilingual markdown variants successfully removed. Dead flags cleared.")
        try:
            write_unified_json(json_file, payload)
            
            warn_deprecated_artifact("aggregated_issues_json", aggr_file, "write", options.strict_deprecations)
            write_unified_json(aggr_file, {"included_sources": include_sources, "issues": issues})
            
            logger.debug(
                "Phase E: aggregated_issues.json written for compatibility "
                "(classification: compatibility_required; replacement: audit_master.json[issue_inventory]). "
                "Path: %s", aggr_file
            )
            write_unified_json(review_json, {"columns": REVIEW_QUEUE_COLUMNS, "rows": review_rows})
            
            try:
                write_audit_master(
                    artifacts_dir=results_dir / "artifacts",
                    aggr_file=aggr_file,
                    json_file=json_file,
                    review_json=review_json,
                    review_xlsx=review_xlsx,
                    issues=issues,
                    review_rows=review_rows,
                    payload=payload,
                    missing=missing,
                    include_sources=include_sources,
                    source_status=source_status,
                    project_root=runtime.project_root,
                    runtime=runtime,
                    options=options,
                )
            except Exception as master_exc:
                logger.error("Failed to write audit_master.json: %s", master_exc)
            
            # Migrate verified translations to staged storage
            try:
                from l10n_audit.core.results_manager import migrate_verified_to_staged
                migrate_verified_to_staged(runtime.project_root, payload)
            except Exception as migrate_exc:
                logger.warning("Failed to migrate verified translations: %s", migrate_exc)

        except Exception as json_exc:
            logger.error("Failed to write unified JSON reports: %s", json_exc)

        artifacts.extend([
            ReportArtifact(name="Final Report (Markdown)", path=str(md_file), format="markdown", category="summary"),
            ReportArtifact(name="Final Report (JSON)", path=str(json_file), format="json", category="summary"),
            ReportArtifact(name="Review Queue (JSON)", path=str(review_json), format="json", category="review"),
        ])

        try:
            write_simple_xlsx(review_rows, REVIEW_QUEUE_COLUMNS, review_xlsx, sheet_name="Review Queue")
            artifacts.append(ReportArtifact(name="Review Queue (Excel)", path=str(review_xlsx), format="xlsx", category="review"))
        except Exception as xlsx_exc:
            logger.warning("Could not write review XLSX: %s", xlsx_exc)

        logger.info("Report aggregator: %d issues aggregated, %d in review queue", len(issues), len(review_rows))
    except Exception as exc:
        logger.warning("Report aggregation failed: %s", exc)

    return artifacts
