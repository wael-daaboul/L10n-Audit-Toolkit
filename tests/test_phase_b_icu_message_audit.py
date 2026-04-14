from pathlib import Path
from unittest.mock import MagicMock

from l10n_audit.audits.icu_message_audit import run_stage
from l10n_audit.models import AuditOptions

def test_icu_message_audit_run_stage_with_paired_injected_state(tmp_path: Path):
    """
    Prove that icu_message_audit can successfully operate from paired pre-hydrated 
    canonical state when injected, fulfilling the Phase B proxy requirements,
    and avoiding raw internal file reads entirely.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    
    # Mocking out the files to verify it DOES NOT read them for locale state
    runtime.en_file.write_text('{"bad_key": "{count, plural, =0{None} other{Many}}" }')
    runtime.ar_file.write_text('{"good_key": "نص عربي"}')

    options = MagicMock(spec=AuditOptions)
    options.write_reports = False

    # Pre-hydrated paired state matching real JSON dictionary shapes
    canonical_en_data = {
        "my_icu": "{count, plural, =0{No trips} one{1 trip} other{{count} trips}}"
    }
    canonical_ar_data = {
        "my_icu": "رحلات" # Literal text only - triggers a high severity ICU mismatch
    }

    issues = run_stage(runtime, options, en_data=canonical_en_data, ar_data=canonical_ar_data)
    
    assert isinstance(issues, list)
    assert len(issues) == 1
    
    issue = issues[0]
    assert issue.key == "my_icu"
    assert issue.issue_type == "icu_literal_text_only"
    assert issue.severity == "high"
    assert issue.extra["audit_source"] == "icu_message_audit"
    assert issue.locale == "en/ar"  # Normalization maps it to paired
    assert "detected_value" in issue.extra
    assert issue.extra["detected_value"] == "{count, plural, =0{No trips} one{1 trip} other{{count} trips}}"
    assert issue.extra["candidate_value"] == "رحلات"
    assert "current_value" not in issue.extra

def test_icu_message_audit_fallback_logs_warn(tmp_path: Path, caplog):
    """
    Ensure the narrow backwards compatibility fallback works but explicitly warns
    when invoked lacking paired injected state.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.locale_format = "json"
    
    # It must fallback to loading this file if paired data isn't supplied
    runtime.en_file.write_text('{"fallback_icu": "{count, plural, =0{Zero} other{Other}}" }', encoding="utf-8")
    runtime.ar_file.write_text('{"fallback_icu": "{count}"}', encoding="utf-8") # mismatch
    
    options = MagicMock(spec=AuditOptions)
    options.write_reports = False

    issues = run_stage(runtime, options)
    
    assert len(issues) >= 1
    assert any(i.key == "fallback_icu" and i.issue_type == "icu_literal_text_only" for i in issues)

    assert "Deprecation: icu_message_audit invoked without paired canonical state" in caplog.text
