import json
from pathlib import Path
from unittest.mock import MagicMock

from l10n_audit.audits.ar_locale_qc import run_stage
from l10n_audit.models import AuditOptions

def test_ar_locale_qc_run_stage_with_paired_injected_state(tmp_path: Path):
    """
    Prove that ar_locale_qc can successfully operate from paired pre-hydrated 
    canonical state when injected, avoiding raw internal file reads entirely.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.glossary_file = tmp_path / "glossary.json"
    runtime.results_dir = tmp_path / "results"
    runtime.code_dirs = []
    runtime.usage_patterns = {}
    runtime.allowed_extensions = []
    runtime.project_profile = "default"
    runtime.locale_format = "json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    
    # Mocking out the files to verify it DOES NOT read them for locale state
    # If it reads these, it will find "bad_key" which we WON'T inject.
    runtime.en_file.write_text('{"bad_key": "Should not be read"}')
    runtime.ar_file.write_text('{"bad_key": "فشل"}')
    
    # Ensure config and glossary exist to avoid file not found errors
    (tmp_path / "config.json").write_text("{}")
    runtime.glossary_file.write_text('{"terms": []}')

    options = MagicMock()
    options.write_reports = False
    options.audit_rules.role_identifiers = []

    # Pre-hydrated paired state matching real JSON dictionary shapes
    canonical_en_data = {
        "greeting": "Hello!!!" # triggers exclamation_style find if ar is also high
    }
    canonical_ar_data = {
        "greeting": "أهلا!!!"
    }

    issues = run_stage(runtime, options, en_data=canonical_en_data, ar_data=canonical_ar_data)
    
    assert isinstance(issues, list)
    # exclamation_style triggers if > 2 punctuation and differs or both high. 
    # Actually let's check for something simpler like suspicious_literal_translation or similar if we can.
    # For now, just verifying it runs and produces output from our injected keys.
    # If it read the files, it would have 'bad_key'.
    keys = {i.key for i in issues}
    assert "bad_key" not in keys
    
    # Prove it can detect from injected data (e.g. exclamation style)
    # Greeting "Hello!!!" vs "أهلا!!!" might trigger exclamation_style.
    assert any(i.key == "greeting" for i in issues)

def test_ar_locale_qc_fallback_logs_warn(tmp_path: Path, caplog):
    """
    Ensure the narrow backwards compatibility fallback works but explicitly warns
    when invoked lacking paired injected state.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.glossary_file = tmp_path / "glossary.json"
    runtime.results_dir = tmp_path / "results"
    runtime.code_dirs = []
    runtime.usage_patterns = {}
    runtime.allowed_extensions = []
    runtime.project_profile = "default"
    runtime.locale_format = "json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    
    # It must fallback to loading these files if paired data isn't supplied
    runtime.en_file.write_text('{"fallback_key": "Hello!!!"}')
    runtime.ar_file.write_text('{"fallback_key": "أهلا!!!"}')
    (tmp_path / "config.json").write_text("{}")
    runtime.glossary_file.write_text('{"terms": []}')
    
    options = MagicMock()
    options.write_reports = False
    options.audit_rules.role_identifiers = []

    issues = run_stage(runtime, options)
    
    assert any(i.key == "fallback_key" for i in issues)
    assert "Deprecation: ar_locale_qc invoked without paired canonical state" in caplog.text
