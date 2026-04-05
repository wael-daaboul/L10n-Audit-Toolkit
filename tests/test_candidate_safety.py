
import pytest
from l10n_audit.reports.report_aggregator import _resolve_candidate_value, _classify_decision_quality, _project_approved_new
from unittest.mock import MagicMock

def resolve(cur, fix):
    return _resolve_candidate_value({}, cur, fix)

def test_brand_safety_identity_gate():
    # 1. Protected Brands (Case Insensitive Identity)
    assert resolve("Bkash account", "Brash account")["conflict_flag"] == "SAFETY_VETO"
    assert resolve("Paytm app", "Part app")["conflict_flag"] == "SAFETY_VETO"
    assert resolve("Use Mercadopago", "Use Mercadona")["conflict_flag"] == "SAFETY_VETO"
    assert resolve("BeTaxi app", "BeeTaxi app")["conflict_flag"] == "SAFETY_VETO"
    
    # 2. Case Preservation (Acronyms only)
    assert resolve("API key", "Api key")["conflict_flag"] == "SAFETY_VETO"
    assert resolve("The OTP is", "The Pin is")["conflict_flag"] == "SAFETY_VETO"
    
    # 3. CamelCase Integrity
    assert resolve("PayTabs", "Pay Tabs")["conflict_flag"] == "SAFETY_VETO"
    assert resolve("FlutterWave", "Flutter Wave")["conflict_flag"] == "SAFETY_VETO"

def test_sentence_initial_allowance():
    # Ordinary capitalization should NOT be blocked by safety gate 
    # (Unless it's a protected brand)
    res = resolve("Submit your form", "Send your document")
    # It might still be blocked by Decision Quality in Phase 8?
    # But Phase 7 should NOT VETO it.
    assert res["conflict_flag"] != "SAFETY_VETO"
    assert res["resolution_mode"] == "suggested_fix"

def test_mechanical_safe_cases():
    # Whitespace cleanup should pass
    res = resolve("Hello  world", "Hello world")
    assert res["resolution_mode"] == "suggested_fix"
    assert res["conflict_flag"] == ""

def test_queue_materialization_output_inspection():
    # Stronger row-materialization evidence for a blocked brand case
    issue = {
        "key": "PAYMENT_INFO",
        "locale": "ar",
        "current_value": "Paytm and Bkash",
        "suggested_fix": "Part and Brash",
        "issue_type": "info_missing",
        "severity": "medium",
        "details": {}
    }
    
    res = _resolve_candidate_value(issue, issue["current_value"], issue["suggested_fix"])
    approved = _project_approved_new(issue, res)
    quality = _classify_decision_quality(issue, res, approved)
    
    # Final "Row" inspection
    row = {
        "suggested_fix": res["candidate_value"],
        "approved_new": approved,
        "notes": res["notes_token"],
        "decision": quality["decision_token"],
        "reason": quality["decision_reason"]
    }
    
    # Assertions on materialized row fields
    assert row["suggested_fix"] == "" # Candidate value must be cleared in conflict
    assert row["approved_new"] == ""  # MUST BE EMPTY
    assert "[CONFLICT:SAFETY_VETO]" in row["notes"]
    assert row["decision"] == "[DQ:BLOCKED]"
    assert row["reason"] == "safety_gate"

def test_mixed_script_safety():
    # Mixed-script identities e.g. Payتم should be protected
    assert resolve("Payتم", "Pay")["conflict_flag"] == "SAFETY_VETO"

