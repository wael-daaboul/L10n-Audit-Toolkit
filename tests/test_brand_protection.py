import pytest
from audits.ar_locale_qc import detect_mixed_script_issues

def test_mixed_script_flags_unknown_latin():
    text = "مرحبا World"
    findings = detect_mixed_script_issues("test_key", text)
    assert len(findings) == 1
    assert findings[0]["issue_type"] == "mixed_script"

def test_mixed_script_ignores_allowed_latin():
    text = "مرحبا Antigravity"
    # Without extra allowed, it should flag
    findings = detect_mixed_script_issues("test_key", text)
    assert len(findings) == 1
    
    # With extra allowed, it should ignore
    extra_allowed = {"antigravity"}
    findings = detect_mixed_script_issues("test_key", text, extra_allowed_latin=extra_allowed)
    assert len(findings) == 0

def test_mixed_script_case_insensitivity():
    text = "مرحبا antigravity"
    extra_allowed = {"Antigravity".casefold()}
    findings = detect_mixed_script_issues("test_key", text, extra_allowed_latin=extra_allowed)
    assert len(findings) == 0
