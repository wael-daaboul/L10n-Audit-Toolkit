from pathlib import Path
from unittest.mock import MagicMock

from l10n_audit.audits.en_locale_qc import run_stage
from l10n_audit.models import AuditIssue, AuditOptions

def test_en_locale_qc_run_stage_with_injected_en_data(tmp_path: Path):
    """
    Prove that en_locale_qc can successfully operate entirely from pre-hydrated 
    canonical EN state when it is injected, fulfilling the Phase B requirements,
    and avoiding raw internal reads.
    """
    runtime = MagicMock()
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.locale_format = "json"
    
    # Mocking out the files to verify it DOES NOT read them for English state
    runtime.en_file.write_text('{"bad_key": "This is totally different."}')
    runtime.ar_file.write_text('{"my_key": "نص عربي"}')

    options = MagicMock(spec=AuditOptions)
    options.write_reports = False

    # Pre-hydrated state matching real JSON dictionary shapes
    canonical_en_data = {
        "my_key": "Please fill all the field",  # triggers grammar finding
    }

    issues = run_stage(runtime, options, en_data=canonical_en_data)
    
    assert isinstance(issues, list)
    assert len(issues) == 1
    
    issue = issues[0]
    assert issue.key == "my_key"
    assert issue.issue_type == "grammar"
    assert issue.extra["audit_source"] == "en_locale_qc"
    assert issue.locale == "en"
    assert "detected_value" in issue.extra
    assert issue.extra["detected_value"] == "Please fill all the field"
    assert "current_value" not in issue.extra

def test_en_locale_qc_fallback_logs_warn(tmp_path: Path, caplog):
    """
    Ensure the narrow backwards compatibility fallback works but explicitly warns.
    """
    runtime = MagicMock()
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.locale_format = "json"
    
    # It must fallback to loading this file if en_data isn't supplied
    runtime.en_file.write_text('{"login_ratting": "rating is 5"}', encoding="utf-8")
    runtime.ar_file.write_text('{"login_ratting": ""}', encoding="utf-8")
    
    options = MagicMock(spec=AuditOptions)
    options.write_reports = False

    issues = run_stage(runtime, options)
    
    assert len(issues) >= 1
    assert any(i.key == "login_ratting" and i.issue_type == "key_naming" for i in issues)

    assert "Deprecation: en_locale_qc invoked without canonical en_data" in caplog.text
