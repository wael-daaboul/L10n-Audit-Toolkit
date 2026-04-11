from l10n_audit.audits.en_grammar_audit import run_stage
from types import SimpleNamespace
from pathlib import Path
from conftest import write_json

def test_grammar_run_stage_applies_fallback_for_empty_issue_category(monkeypatch, tmp_path: Path):
    runtime = SimpleNamespace(
        en_file=tmp_path / "en.json",
        source_locale="en",
        target_locales=("ar",),
        locale_format="json",
    )
    write_json(runtime.en_file, {"test_key": "This are test."})
    
    # Mock build_languagetool_findings to return a row with empty issue_type
    mock_lt_row = {
        "key": "test_key",
        "issue_type": "",
        "rule_id": "TEST_RULE",
        "message": "Test message",
        "old": "This are test.",
        "new": "This is a test.",
        "replacements": "This is a test.",
        "context": "This are test.",
        "offset": 0,
        "error_length": 14,
    }
    
    def mock_build_languagetool_findings(*args, **kwargs):
        return "mock-mode", [mock_lt_row], None
        
    monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.build_languagetool_findings", mock_build_languagetool_findings)
    monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.build_custom_findings", lambda *args, **kwargs: [])
    
    options = SimpleNamespace(write_reports=False)
    
    issues = run_stage(runtime, options)
    
    assert len(issues) == 1
    assert issues[0].issue_type == "grammar", f"Expected 'grammar', got '{issues[0].issue_type}'"
