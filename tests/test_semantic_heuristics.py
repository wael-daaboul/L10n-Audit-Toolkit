import pytest
from l10n_audit.audits.ar_semantic_qc import detect_semantic_findings

def test_possible_meaning_loss_threshold():
    bundle = {"semantic_flags": ["missing_action:save"]}
    en_text = "Please save your work."
    
    # 1 word Arabic text (ar_text = "احفظ")
    ar_text = "احفظ"
    
    # Default threshold is 3. ar_word_count is 1. Should be skipped.
    findings = detect_semantic_findings("key", en_text, ar_text, bundle)
    assert not any(f["issue_type"] == "possible_meaning_loss" for f in findings)
    
    # If we lower threshold to 0, it should be flagged
    findings = detect_semantic_findings("key", en_text, ar_text, bundle, short_label_threshold=0)
    assert any(f["issue_type"] == "possible_meaning_loss" for f in findings)

def test_glossary_approved_whitelist():
    bundle = {"has_context_sensitive_terms": True, "semantic_flags": ["en:ambiguous"]}
    en_text = "Select Account"
    ar_text = "اختر الحساب"
    
    # Without glossary, it should flag
    findings = detect_semantic_findings("key", en_text, ar_text, bundle)
    assert any(f["issue_type"] == "context_sensitive_meaning" for f in findings)
    
    # With glossary, it should be whitelisted
    approved = {("select account", "اختر الحساب")}
    findings = detect_semantic_findings("key", en_text, ar_text, bundle, glossary_approved_pairs=approved)
    assert not any(f["issue_type"] == "context_sensitive_meaning" for f in findings)

def test_disabled_robotic_fixes():
    bundle = {
        "has_context_sensitive_terms": True, 
        "semantic_flags": ["missing_action:save", "en:ambiguous"]
    }
    en_text = "Save Profile"
    ar_text = "الملف الشخصي" # Missing "Save"
    
    findings = detect_semantic_findings("key", en_text, ar_text, bundle, short_label_threshold=0)
    
    for f in findings:
        if f["issue_type"] == "possible_meaning_loss":
            assert f["candidate_value"] == "احفظ الملف الشخصي"
        elif f["issue_type"] == "context_sensitive_meaning":
            assert f["candidate_value"] == ""
        assert f["fix_mode"] == "review_required"
