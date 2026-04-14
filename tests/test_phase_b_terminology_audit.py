import json
from pathlib import Path
from unittest.mock import MagicMock

from l10n_audit.audits.terminology_audit import run_stage
from l10n_audit.models import AuditOptions

def test_terminology_audit_run_stage_with_paired_injected_state(tmp_path: Path):
    """
    Prove that terminology_audit can successfully operate from paired pre-hydrated 
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
    
    # Glossary setup: define a term match that SHOULD trigger a finding
    # Term: "Admin" (en), Approved: "المسؤول" (ar), Forbidden: ["سوبر بن"]
    glossary_content = {
        "terms": [
            {
                "term_en": "Admin",
                "approved_ar": "المسؤول",
                "forbidden_ar": ["سوبر بن"]
            }
        ]
    }
    runtime.glossary_file.write_text(json.dumps(glossary_content))
    
    # Pre-hydrated paired state matching real JSON dictionary shapes
    canonical_en_data = {
        "admin_label": "Admin" 
    }
    canonical_ar_data = {
        "admin_label": "سوبر بن" # Forbidden term used
    }

    # Ensure results dir exists to avoid file not found
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)

    options = MagicMock()
    options.write_reports = False
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []

    issues = run_stage(runtime, options, en_data=canonical_en_data, ar_data=canonical_ar_data)
    
    assert isinstance(issues, list)
    
    # If it read the files, it would have 'bad_key'.
    keys = {i.key for i in issues}
    assert "bad_key" not in keys
    
    # If it correctly read injected data and glossary, it should detect the violation
    # "Admin" source, but forbidden "سوبر بن" used instead of approved "المسؤول"
    assert any("admin_label" == i.key for i in issues)

def test_terminology_audit_fallback_logs_warn(tmp_path: Path, caplog):
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
    runtime.en_file.write_text('{"fallback_key": "Admin"}')
    runtime.ar_file.write_text('{"fallback_key": "سوبر بن"}')
    
    glossary_content = {
        "terms": [
            {
                "term_en": "Admin",
                "approved_ar": "المسؤول",
                "forbidden_ar": ["سوبر بن"]
            }
        ]
    }
    runtime.glossary_file.write_text(json.dumps(glossary_content))
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    
    options = MagicMock()
    options.write_reports = False
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []

    issues = run_stage(runtime, options)
    
    assert any("fallback_key" == i.key for i in issues)
    assert "Deprecation: terminology_audit invoked without paired canonical state" in caplog.text
