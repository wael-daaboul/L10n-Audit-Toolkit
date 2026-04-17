"""Phase 8 — Review / Report / Apply Alignment for AI Outcomes.

These tests verify that AI outcome decision fields (verified, needs_review,
ai_outcome_decision, semantic_gate_status, semantic_reason_codes, review_reason)
are correctly surfaced through normalize_ai_review and build_review_queue.

Routing semantics validated:
* safe    → verified=True, needs_review=False, approved_new may be filled,
            ai_outcome_decision="safe", no review_reason
* review  → verified=False, needs_review=True, approved_new blocked,
            ai_outcome_decision="review", review_reason shows reason codes
* reject  → must not appear in the issue list at all (dropped by semantic gate)
"""

from __future__ import annotations

import json
import pytest

from l10n_audit.core.audit_report_utils import (
    _ai_semantic_review_reason,
    normalize_ai_review,
)
from l10n_audit.reports.report_aggregator import build_review_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runtime(tmp_path):
    rt = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    rt.en_file.write_text(json.dumps({"greet.msg": "Hello", "pay.title": "Payment"}), encoding="utf-8")
    rt.ar_file.write_text(json.dumps({"greet.msg": "مرحبا", "pay.title": "الدفع"}), encoding="utf-8")
    return rt


# ---------------------------------------------------------------------------
# 1. _ai_semantic_review_reason helper
# ---------------------------------------------------------------------------


def test_reason_helper_returns_empty_for_safe():
    assert _ai_semantic_review_reason("safe", []) == ""
    assert _ai_semantic_review_reason("safe", ["semantic_concept_injection"]) == ""


def test_reason_helper_returns_text_for_review():
    result = _ai_semantic_review_reason("review", ["semantic_concept_injection", "semantic_polarity_mismatch"])
    assert "concept injection" in result
    assert "polarity mismatch" in result


def test_reason_helper_returns_text_for_reject():
    result = _ai_semantic_review_reason("reject", ["semantic_number_mismatch"])
    assert "number mismatch" in result


def test_reason_helper_uses_code_verbatim_when_not_in_map():
    result = _ai_semantic_review_reason("review", ["unknown_custom_code"])
    assert "unknown_custom_code" in result


def test_reason_helper_fallback_no_codes():
    result = _ai_semantic_review_reason("review", [])
    assert "review" in result
    assert result.startswith("AI semantic review:")


# ---------------------------------------------------------------------------
# 2. normalize_ai_review — field propagation
# ---------------------------------------------------------------------------


def _safe_finding(key="greet.msg", suggestion="مرحباً"):
    return {
        "key": key,
        "verified": True,
        "needs_review": False,
        "issue_type": "ai_suggestion",
        "severity": "info",
        "message": "AI Suggestion: greet",
        "source": "Hello",
        "original_source": "Hello",
        "target": "مرحبا",
        "suggestion": suggestion,
        "extra": {
            "ai_outcome_decision": "safe",
            "semantic_gate_status": "accept",
            "semantic_reason_codes": [],
        },
    }


def _suspicious_finding(key="pay.title"):
    return {
        "key": key,
        "verified": False,
        "needs_review": True,
        "issue_type": "ai_suggestion",
        "severity": "info",
        "message": "AI Suggestion: pay",
        "source": "Payment",
        "original_source": "Payment",
        "target": "الدفع",
        "suggestion": "التحويل المالي",
        "extra": {
            "ai_outcome_decision": "review",
            "semantic_gate_status": "suspicious",
            "semantic_reason_codes": ["semantic_concept_injection"],
        },
    }


def test_normalize_safe_candidate_propagates_verified():
    result = normalize_ai_review({"findings": [_safe_finding()]})
    assert len(result) == 1
    issue = result[0]
    assert issue["verified"] is True
    assert issue["needs_review"] is False


def test_normalize_safe_candidate_sets_ai_outcome_fields():
    result = normalize_ai_review({"findings": [_safe_finding()]})
    issue = result[0]
    assert issue["ai_outcome_decision"] == "safe"
    assert issue["semantic_gate_status"] == "accept"


def test_normalize_safe_candidate_no_review_reason():
    result = normalize_ai_review({"findings": [_safe_finding()]})
    issue = result[0]
    details = issue.get("details", {})
    assert not details.get("review_reason", "")


def test_normalize_suspicious_candidate_propagates_needs_review():
    result = normalize_ai_review({"findings": [_suspicious_finding()]})
    assert len(result) == 1
    issue = result[0]
    assert issue["verified"] is False
    assert issue["needs_review"] is True


def test_normalize_suspicious_candidate_sets_ai_outcome_fields():
    result = normalize_ai_review({"findings": [_suspicious_finding()]})
    issue = result[0]
    assert issue["ai_outcome_decision"] == "review"
    assert issue["semantic_gate_status"] == "suspicious"


def test_normalize_suspicious_candidate_builds_review_reason():
    result = normalize_ai_review({"findings": [_suspicious_finding()]})
    issue = result[0]
    details = issue.get("details", {})
    review_reason = details.get("review_reason", "")
    assert review_reason, "review_reason must be non-empty for suspicious candidate"
    assert "concept injection" in review_reason


def test_normalize_suspicious_candidate_reason_codes_visible():
    result = normalize_ai_review({"findings": [_suspicious_finding()]})
    issue = result[0]
    details = issue.get("details", {})
    assert "semantic_reason_codes" in details
    assert "semantic_concept_injection" in details["semantic_reason_codes"]


def test_normalize_handles_missing_extra_gracefully():
    """Row with no 'extra' dict should not raise and should produce safe defaults."""
    row = {
        "key": "greet.msg",
        "suggestion": "مرحباً",
        "source": "Hello",
    }
    result = normalize_ai_review({"findings": [row]})
    assert len(result) == 1
    issue = result[0]
    assert issue["verified"] is False
    assert issue["needs_review"] is False
    assert issue["ai_outcome_decision"] == ""
    assert issue["semantic_gate_status"] == ""


# ---------------------------------------------------------------------------
# 3. build_review_queue — AI outcome visibility in review rows
# ---------------------------------------------------------------------------


def test_build_review_queue_safe_ai_visible_outcome(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_safe_finding()]})
    rows = build_review_queue(issues, rt)
    assert len(rows) == 1, "Safe AI candidate must appear in review queue"
    row = rows[0]
    assert row["ai_outcome_decision"] == "safe"
    assert row["semantic_gate_status"] == "accept"


def test_build_review_queue_safe_ai_not_blocked(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_safe_finding()]})
    rows = build_review_queue(issues, rt)
    row = rows[0]
    # Safe AI candidates have no review_reason → not blocked by step 5 of _project_approved_new.
    assert row.get("review_reason", "") == ""


def test_build_review_queue_suspicious_ai_visible_outcome(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_suspicious_finding()]})
    rows = build_review_queue(issues, rt)
    assert len(rows) == 1, "Suspicious AI candidate must still appear in review queue (for visibility)"
    row = rows[0]
    assert row["ai_outcome_decision"] == "review"
    assert row["semantic_gate_status"] == "suspicious"


def test_build_review_queue_suspicious_ai_review_required(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_suspicious_finding()]})
    rows = build_review_queue(issues, rt)
    row = rows[0]
    assert row["needs_review"] == "Yes"
    assert row["approved_new"] == ""


def test_build_review_queue_suspicious_ai_review_reason_visible(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_suspicious_finding()]})
    rows = build_review_queue(issues, rt)
    row = rows[0]
    review_reason = row.get("review_reason", "")
    assert review_reason, "review_reason must be visible in the review row for suspicious AI candidate"
    assert "concept injection" in review_reason


def test_build_review_queue_semantic_reason_codes_in_notes(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_suspicious_finding()]})
    rows = build_review_queue(issues, rt)
    row = rows[0]
    # review_reason surfaces through notes (notes contains concatenated message + tokens)
    # At minimum the review_reason itself must be visible in the row.
    assert row.get("review_reason", "")


def test_build_review_queue_safe_ai_does_not_appear_as_suspicious(tmp_path):
    rt = _runtime(tmp_path)
    issues = normalize_ai_review({"findings": [_safe_finding()]})
    rows = build_review_queue(issues, rt)
    row = rows[0]
    # Must NOT carry a review_reason (which would incorrectly block auto-projection)
    assert row.get("review_reason", "") == ""
    assert row["ai_outcome_decision"] == "safe"


# ---------------------------------------------------------------------------
# 4. apply safety gate — verified flag propagation
# ---------------------------------------------------------------------------


def test_safe_ai_candidate_is_apply_eligible():
    """build_fix_plan must include safe AI candidates when verified=True."""
    from l10n_audit.fixes.apply_safe_fixes import build_fix_plan

    issue = {
        "key": "greet.msg",
        "source": "ai_review",
        "issue_type": "ai_suggestion",
        "locale": "ar",
        "verified": True,
        "needs_review": False,
        "ai_outcome_decision": "safe",
        "details": {"old": "مرحبا", "new": "مرحباً"},
    }
    plan = build_fix_plan([issue])
    plan_keys = [item["key"] for item in plan]
    assert "greet.msg" in plan_keys, "Safe AI candidate must be eligible for apply"


def test_suspicious_ai_candidate_is_not_apply_eligible():
    """build_fix_plan must exclude AI candidates with verified=False."""
    from l10n_audit.fixes.apply_safe_fixes import build_fix_plan

    issue = {
        "key": "pay.title",
        "source": "ai_review",
        "issue_type": "ai_suggestion",
        "locale": "ar",
        "verified": False,
        "needs_review": True,
        "ai_outcome_decision": "review",
        "details": {"old": "الدفع", "new": "التحويل المالي"},
    }
    plan = build_fix_plan([issue])
    plan_keys = [item["key"] for item in plan]
    assert "pay.title" not in plan_keys, "Suspicious AI candidate must NOT be apply-eligible"


def test_normalize_ai_review_empty_payload():
    result = normalize_ai_review({"findings": []})
    assert result == []


def test_normalize_ai_review_mixed_safe_and_suspicious():
    """Multiple findings in one payload must each independently propagate their outcome."""
    payload = {
        "findings": [
            _safe_finding("greet.msg"),
            _suspicious_finding("pay.title"),
        ]
    }
    results = normalize_ai_review(payload)
    assert len(results) == 2
    by_key = {r["key"]: r for r in results}
    assert by_key["greet.msg"]["verified"] is True
    assert by_key["greet.msg"]["needs_review"] is False
    assert by_key["pay.title"]["verified"] is False
    assert by_key["pay.title"]["needs_review"] is True
