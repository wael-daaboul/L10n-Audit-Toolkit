from l10n_audit.audits.basic_consistency_audit import run_stage
from l10n_audit.models import AuditOptions

def test_basic_consistency_audit_identical():
    # Setup injected canonical state
    en_data = {"key1": "Hello", "key2": "World"}
    ar_data = {"key1": "مرحبا", "key2": "World"} # key2 is identically translated
    
    # Run the stage
    issues = run_stage(None, AuditOptions(), en_data=en_data, ar_data=ar_data)
    
    assert len(issues) == 1
    issue = issues[0]
    assert issue.key == "key2"
    assert issue.issue_type == "identical_translation"
    assert issue.extra["detected_value"] == "World"  # Was adapter-mapped from 'old'
    assert issue.extra["candidate_value"] == ""      # Was adapter-mapped from 'new'

def test_basic_consistency_audit_ignores_blanks():
    en_data = {"key1": "   ", "key2": "Good"}
    ar_data = {"key1": "   ", "key2": ""}
    
    issues = run_stage(None, AuditOptions(), en_data=en_data, ar_data=ar_data)
    
    # Should skip these based on the logic
    assert len(issues) == 0
