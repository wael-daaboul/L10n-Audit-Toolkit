
import pytest
from l10n_audit.reports.report_aggregator import _resolve_candidate_value, _project_approved_new, _classify_decision_quality

def get_row_fields(cur, fix, severity="info", needs_review=False):
    issue = {
        "current_value": cur,
        "suggested_fix": fix,
        "severity": severity,
        "needs_review": needs_review,
        "details": {}
    }
    res = _resolve_candidate_value(issue, cur, fix)
    approved = _project_approved_new(issue, res)
    dq = _classify_decision_quality(issue, res, approved)
    return approved, dq

def test_refined_dq_safe_bucket():
    # 1. Whitespace (Mechanical) -> If cur.strip() == fix.strip(), resolution is current_value -> Empty projection.
    approved, dq = get_row_fields("  hello  ", "hello")
    assert approved == "" # Deduplicated to current value
    
    # 2. Punctuation Normalization (Mechanical) -> SAFE_AUTO_PROJECTED
    approved, dq = get_row_fields("Hello", "Hello.")
    assert approved == "Hello."
    assert dq["decision_quality"] == "safe_auto_projected"
    
    # 3. Harmless Case Normalization -> SAFE_AUTO_PROJECTED
    # Note: Phase 7 is case-sensitive, so brands are NOT in this bucket.
    approved, dq = get_row_fields("EMAIL", "Email")
    assert approved == "Email"
    assert dq["decision_quality"] == "safe_auto_projected"
    
    # 4. Low-risk Typo Correction (mision -> mission) -> SAFE_AUTO_PROJECTED
    approved, dq = get_row_fields("The mision is", "The mission is")
    assert approved == "The mission is"
    assert dq["decision_quality"] == "safe_auto_projected"

def test_phase8_semantic_blocking():
    # 5. Semantic Rewrite (Submit -> Send) -> SUGGESTION_ONLY
    approved, dq = get_row_fields("Submit your form", "Send your document")
    assert approved == "" # Semantic change is NOT mechanical
    assert dq["decision_quality"] == "suggestion_only"
    
    # 6. Phrase Expansion (Pay -> Pay Now) -> BLOCKED by Pattern Completion Guard v1
    approved, dq = get_row_fields("Pay", "Pay Now")
    assert approved == "" # expansion is NOT mechanical
    assert dq["decision_quality"] == "blocked"

def test_safety_priority_over_dq():
    # 7. Brand safety veto is now exact-case (Phase 7 tightening).
    # Bkash -> bKash is now a CONFLICT (identity violation).
    # This MUST block approved_new and result in dq="blocked"
    approved, dq = get_row_fields("Bkash", "bKash")
    assert approved == ""
    assert dq["decision_quality"] == "blocked"
    assert dq["decision_reason"] == "safety_gate"

def test_levenshtein_distance_logic():
    # Ensure dist > 2 is blocked (Submit -> Send)
    from l10n_audit.reports.report_aggregator import _levenshtein_distance
    assert _levenshtein_distance("submit", "send") > 2
    assert _levenshtein_distance("mision", "mission") == 1
