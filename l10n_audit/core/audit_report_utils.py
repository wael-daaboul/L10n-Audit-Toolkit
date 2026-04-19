#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from l10n_audit.core.deprecation_warnings import warn_deprecated_artifact
from l10n_audit.core.audit_runtime import write_json, compute_text_hash

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

REPORT_FILE_MAP = {
    "localization": ".cache/raw_tools/localization/localization_audit_pro.json",
    "locale_qc": ".cache/raw_tools/en_locale_qc/en_locale_qc_report.json",
    "ar_locale_qc": ".cache/raw_tools/ar_locale_qc/ar_locale_qc_report.json",
    "ar_semantic_qc": ".cache/raw_tools/ar_semantic_qc/ar_semantic_qc_report.json",
    "grammar": ".cache/raw_tools/grammar/grammar_audit_report.json",
    "terminology": ".cache/raw_tools/terminology/terminology_violations.json",
    "placeholders": ".cache/raw_tools/placeholders/placeholder_audit_report.json",
    "icu_message_audit": ".cache/raw_tools/icu_message_audit/icu_message_audit_report.json",
    "ai_review": ".cache/raw_tools/ai_review/ai_review_report.json",
}

SOURCE_GROUPS = {
    "localization": "localization_key_issues",
    "terminology": "terminology_violations",
    "placeholders": "placeholder_issues",
    "grammar": "grammar_issues",
    "locale_qc": "locale_qc_issues",
    "ar_locale_qc": "locale_qc_issues",
    "ar_semantic_qc": "locale_qc_issues",
    "icu_message_audit": "icu_message_issues",
}


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 99)


def normalize_severity(severity: str | None, fallback: str = "info") -> str:
    normalized = str(severity or fallback).strip().lower()
    if normalized == "warning":
        return "medium"
    if normalized not in SEVERITY_ORDER:
        return fallback
    return normalized


def _severity_for_localization(issue_type: str) -> str:
    if issue_type in {"missing_in_both", "confirmed_missing_key"}:
        return "critical"
    if issue_type in {"missing_in_ar", "missing_in_en", "empty_ar", "empty_en"}:
        return "high"
    if issue_type == "needs_manual_review":
        return "medium"
    if issue_type in {"context_sensitive_term_conflict", "role_entity_misalignment"}:
        return "medium"
    if issue_type in {"in_ar_not_en", "in_en_not_ar"}:
        return "medium"
    if issue_type in {"unused_ar", "unused_en", "confirmed_unused_key"}:
        return "low"
    if issue_type == "possibly_dynamic_usage":
        return "info"
    return "info"


def _severity_for_locale_qc(issue_type: str) -> str:
    if issue_type in {"placeholder_mismatch", "key_naming"}:
        return "high"
    if issue_type in {"grammar", "ui_wording"}:
        return "medium"
    if issue_type in {"duplicate_value"}:
        return "info"
    return "low"


def _severity_for_ar_locale_qc(issue_type: str) -> str:
    if issue_type == "forbidden_term":
        return "high"
    if issue_type in {"context_sensitive_term_conflict", "role_entity_misalignment"}:
        return "medium"
    if issue_type == "inconsistent_translation":
        return "medium"
    if issue_type in {"whitespace", "spacing", "punctuation_spacing", "bracket_spacing", "slash_spacing"}:
        return "low"
    if issue_type in {"long_ui_string", "similar_phrase_variation", "exclamation_style", "suspicious_literal_translation"}:
        return "info"
    return "low"


def _severity_for_ar_semantic_qc(issue_type: str) -> str:
    if issue_type in {"sentence_shape_mismatch", "message_label_mismatch", "possible_meaning_loss"}:
        return "medium"
    if issue_type == "context_sensitive_meaning":
        return "info"
    return "low"


def _severity_for_grammar(issue_type: str, row: dict[str, Any]) -> str:
    rule_id = str(row.get("rule_id", ""))
    if rule_id == "LANGUAGETOOL_ERROR":
        return "medium"
    if issue_type in {"misspelling", "typographical"}:
        return "low"
    if issue_type in {"grammar", "style", "uncategorized"}:
        return "medium"
    return "low"


def _severity_for_terminology(issue_type: str) -> str:
    if issue_type == "forbidden_term":
        return "high"
    if issue_type == "hard_violation":
        return "medium"
    if issue_type == "soft_terminology_drift":
        return "low"
    return "medium"


def _severity_for_placeholder(issue_type: str) -> str:
    if issue_type in {"missing_in_ar", "missing_in_en", "count_mismatch", "format_mismatch"}:
        return "high"
    if issue_type in {"renamed_placeholder", "mixed_placeholder_style"}:
        return "medium"
    if issue_type == "order_mismatch":
        return "low"
    return "info"


def _severity_for_icu(issue_type: str) -> str:
    if issue_type in {"icu_syntax_error", "icu_branch_incomplete", "icu_literal_text_only"}:
        return "high"
    if issue_type in {"icu_branch_mismatch", "icu_placeholder_mismatch"}:
        return "medium"
    if issue_type == "icu_suspicious_variation":
        return "info"
    return "low"


def load_json_report(path: Path) -> dict[str, Any] | None:
    import json

    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_localization(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings = payload.get("findings", [])
    issues: list[dict[str, Any]] = []
    for row in findings:
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "localization",
                "group": SOURCE_GROUPS["localization"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_localization(issue_type)),
                "message": str(row.get("message", "")),
                "locale": str(row.get("locale", "")),
                "details": row,
                "recommendation": "Trust confirmed static usage first, then fix confirmed missing keys and review ambiguous locale alignment items manually.",
            }
        )
    return issues


def normalize_locale_qc(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "locale_qc",
                "group": SOURCE_GROUPS["locale_qc"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_locale_qc(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "en",
                "details": row,
                "recommendation": "Apply safe text cleanup for deterministic issues, then review wording-related findings.",
            }
        )
    return issues


def normalize_ar_locale_qc(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "ar_locale_qc",
                "group": SOURCE_GROUPS["ar_locale_qc"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_ar_locale_qc(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "ar",
                "details": row,
                "recommendation": "Apply deterministic Arabic cleanup fixes safely, then review terminology and wording findings in context.",
            }
        )
    return issues


def normalize_ar_semantic_qc(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "ar_semantic_qc",
                "group": SOURCE_GROUPS["ar_semantic_qc"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_ar_semantic_qc(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "ar",
                "details": row,
                "recommendation": "Treat semantic Arabic suggestions as reviewer guidance and approve only after checking the live UI context.",
            }
        )
    return issues


def normalize_grammar(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "grammar",
                "group": SOURCE_GROUPS["grammar"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_grammar(issue_type, row)),
                "message": str(row.get("message", "")),
                "locale": "en",
                "details": row,
                "recommendation": "Review grammar suggestions for product tone before applying broader rewrites.",
            }
        )
    return issues


def normalize_terminology(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("violations", []):
        issue_type = str(row.get("violation_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "terminology",
                "group": SOURCE_GROUPS["terminology"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_terminology(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "ar",
                "details": row,
                "recommendation": "Use hard violations to block release decisions and treat softer terminology drift as a reviewer prompt.",
            }
        )
    return issues


def normalize_placeholders(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "placeholders",
                "group": SOURCE_GROUPS["placeholders"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_placeholder(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "en/ar",
                "details": row,
                "recommendation": "Keep placeholder names, counts, and styles aligned across locales.",
            }
        )
    return issues


def normalize_icu_message_audit(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        issue_type = str(row.get("issue_type") or "").strip() or "unknown"
        issues.append(
            {
                "source": "icu_message_audit",
                "group": SOURCE_GROUPS["icu_message_audit"],
                "key": str(row.get("key", "")),
                "issue_type": issue_type,
                "severity": normalize_severity(row.get("severity"), _severity_for_icu(issue_type)),
                "message": str(row.get("message", "")),
                "locale": "en/ar",
                "details": row,
                "recommendation": "Keep ICU syntax, branch sets, and nested placeholders aligned across locales before shipping formatted messages.",
            }
        )
    return issues

# Maps internal semantic reason codes (from the AI acceptance gate) to concise
# human-readable text shown in the review queue's review_reason column.
# Codes not present here are left as-is (raw code is still surfaced).
_AI_REASON_CODE_TEXT: dict[str, str] = {
    "semantic_concept_injection": "concept injection",
    "semantic_polarity_mismatch": "polarity mismatch",
    "semantic_number_mismatch": "number mismatch",
    "semantic_named_entity_mismatch": "named entity mismatch",
    "semantic_short_text_expansion": "short-string expansion",
    "semantic_key_concept_loss": "key concept loss",
    "semantic_intent_shift": "intent shift",
}


def _ai_semantic_review_reason(ai_outcome_decision: str, reason_codes: list) -> str:
    """Build concise deterministic review_reason from AI outcome decision and semantic reason codes.

    Returns a non-empty string only for suspicious/reject decisions, so that
    safe candidates do not have a spurious review_reason that would block
    auto-projection in ``_project_approved_new``.
    """
    if ai_outcome_decision not in ("review", "reject"):
        return ""
    readable = [_AI_REASON_CODE_TEXT.get(code, code) for code in (reason_codes or [])]
    if readable:
        return f"AI semantic review: {', '.join(readable)}"
    return f"AI semantic review: {ai_outcome_decision}"


def normalize_ai_review(payload: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in payload.get("findings", []):
        # v1.3.1 - Robust extraction for merging
        suggestion = (
            str(row.get("suggestion") or "") or
            str(row.get("candidate_value") or "") or
            str(row.get("approved_new") or "") or
            str(row.get("suggested_fix") or "")
        ).strip()

        old_val = str(row.get("source") or row.get("original_source") or row.get("source_old_value") or "")

        # --- Phase 8: Surface AI outcome decision fields ---
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}

        # Propagate needs_review (bool) — used by _project_approved_new and
        # _classify_decision_quality to block auto-apply for suspicious candidates.
        needs_review_raw = row.get("needs_review")
        if needs_review_raw is None:
            needs_review_raw = extra.get("needs_review")
        needs_review = bool(needs_review_raw) if needs_review_raw is not None else False

        # Propagate verified (bool) — used by build_fix_plan to gate apply-eligibility.
        verified_raw = row.get("verified")
        if verified_raw is None:
            verified_raw = extra.get("verified")
        verified = bool(verified_raw) if verified_raw is not None else False

        ai_outcome_decision = str(extra.get("ai_outcome_decision", "") or "")
        semantic_gate_status = str(extra.get("semantic_gate_status", "") or "")
        semantic_reason_codes = extra.get("semantic_reason_codes") if isinstance(
            extra.get("semantic_reason_codes"), list
        ) else []

        # Build a human-readable review_reason for suspicious/reject decisions.
        review_reason = _ai_semantic_review_reason(ai_outcome_decision, semantic_reason_codes)

        # Enriched details: copy of the raw row plus the derived AI-outcome fields
        # so that build_review_queue can pick them up via issue.get("details").
        enriched_details: dict[str, Any] = {
            **row,
            "ai_outcome_decision": ai_outcome_decision,
            "semantic_gate_status": semantic_gate_status,
            "semantic_reason_codes": semantic_reason_codes,
        }
        if review_reason:
            enriched_details["review_reason"] = review_reason

        issues.append(
            {
                "source": "ai_review",
                "group": "ai_suggestions",
                "key": str(row.get("key", "")),
                "issue_type": "ai_suggestion",
                "severity": "info",
                "message": str(row.get("identified_issue") or row.get("message") or "AI Review feedback"),
                "locale": str(row.get("locale") or "ar"),
                "suggested_fix": suggestion,
                "approved_new": suggestion,
                "source_old_value": old_val,
                "source_hash": str(row.get("source_hash") or compute_text_hash(old_val)),
                "suggested_hash": str(row.get("suggested_hash") or compute_text_hash(suggestion)),
                # Phase 8: AI outcome decision fields surfaced at top-level
                "verified": verified,
                "needs_review": needs_review,
                "ai_outcome_decision": ai_outcome_decision,
                "semantic_gate_status": semantic_gate_status,
                "details": enriched_details,
                "provenance": str(row.get("provenance") or "ai_review|ai_suggestion"),
                "recommendation": "Review AI suggestions for accuracy and fit before applying to your final translation set.",
            }
        )
    return issues


NORMALIZERS = {
    "localization": normalize_localization,
    "locale_qc": normalize_locale_qc,
    "ar_locale_qc": normalize_ar_locale_qc,
    "ar_semantic_qc": normalize_ar_semantic_qc,
    "grammar": normalize_grammar,
    "terminology": normalize_terminology,
    "placeholders": normalize_placeholders,
    "icu_message_audit": normalize_icu_message_audit,
    "ai_review": normalize_ai_review,
}


def dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for issue in issues:
        details = issue.get("details", {})
        fingerprint = (
            str(issue.get("source", "")),
            str(issue.get("key", "")),
            str(issue.get("issue_type", "")),
            str(details.get("old", details.get("english_value", ""))),
            str(issue.get("message", "")),
        )
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(issue)
    return unique


def sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        issues,
        key=lambda issue: (
            severity_rank(str(issue.get("severity", "info"))),
            str(issue.get("source", "")),
            str(issue.get("key", "")),
            str(issue.get("issue_type", "")),
        ),
    )


def load_all_report_issues(
    results_dir: Path,
    include_sources: set[str] | None = None,
    options: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    reports: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    missing: list[str] = []

    for source, filename in REPORT_FILE_MAP.items():
        if include_sources is not None and source not in include_sources:
            continue
        
        file_path = results_dir / filename
        if not file_path.exists() and ".cache/raw_tools" in filename:
            legacy_path = results_dir / filename.replace(".cache/raw_tools", "per_tool")
            if legacy_path.exists():
                strict = getattr(options, "strict_deprecations", False) if options else False
                warn_deprecated_artifact("per_tool_json", legacy_path, "read", strict_mode=strict)
                file_path = legacy_path
                
        payload = load_json_report(file_path)
        if payload is None:
            missing.append(str(file_path.relative_to(results_dir)))
            continue
        reports[source] = payload
        issues.extend(NORMALIZERS[source](payload))

    issues = sort_issues(dedupe_issues(issues))
    return reports, issues, missing


def load_hydrated_report(report_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Loads a single aggregated JSON report (final_audit_report.json) and hydratess findings."""
    payload = load_json_report(report_path)
    if payload is None:
        return {}, [], [str(report_path)]
    
    issues = payload.get("issues", [])
    for issue in issues:
        issue["issue_type"] = str(issue.get("issue_type") or "").strip() or "unknown"
    return payload, issues, []


def summarize_issues(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_issues": len(issues),
        "by_severity": dict(sorted(Counter(str(issue["severity"]) for issue in issues).items())),
        "by_source": dict(sorted(Counter(str(issue["source"]) for issue in issues).items())),
        "by_issue_type": dict(sorted(Counter(str(issue["issue_type"]) for issue in issues).items())),
    }


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, set):
        normalized = [_to_json_safe(item) for item in value]
        def _sort_key(item: Any) -> str:
            try:
                return json.dumps(item, ensure_ascii=False, sort_keys=True)
            except TypeError:
                return str(item)
        return sorted(normalized, key=_sort_key)
    return value


def write_unified_json(path: Path, payload: dict[str, Any]) -> None:
    write_json(_to_json_safe(payload), path)
