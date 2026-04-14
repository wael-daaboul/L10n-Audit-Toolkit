from pathlib import Path
from unittest.mock import MagicMock

from l10n_audit.audits.ar_semantic_qc import run_stage
from l10n_audit.models import AuditOptions

def test_ar_semantic_qc_run_stage_with_paired_injected_state(tmp_path: Path):
    """
    Prove that ar_semantic_qc can successfully operate from paired pre-hydrated 
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
    
    # Pre-hydrated paired state matching real JSON dictionary shapes
    canonical_en_data = {
        "save_action": "Save the current changes now." 
    }
    canonical_ar_data = {
        "save_action": "نعم" # triggers mismatch because "Save" is missing from "نعم"
    }

    # Ensure glossary and results dir exist to avoid file not found
    runtime.glossary_file.write_text('{"terms": []}')
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)

    options = MagicMock()
    options.write_reports = False
    options.ai_review.short_label_threshold = 3
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []

    issues = run_stage(runtime, options, en_data=canonical_en_data, ar_data=canonical_ar_data)
    
    assert isinstance(issues, list)
    
    # If it read the files, it would have 'bad_key'.
    keys = {i.key for i in issues}
    assert "bad_key" not in keys
    
    # If it correctly read injected data, it should detect the mismatch for save_action
    # "Save" vs "نعم" should trip possible_meaning_loss
    assert any("save_action" == i.key for i in issues)

def test_ar_semantic_qc_fallback_logs_warn(tmp_path: Path, caplog):
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
    runtime.en_file.write_text('{"fallback_key": "Save the changes."}')
    runtime.ar_file.write_text('{"fallback_key": "نعم"}')
    runtime.glossary_file.write_text('{"terms": []}')
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    
    options = MagicMock()
    options.write_reports = False
    options.ai_review.short_label_threshold = 3
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []

    issues = run_stage(runtime, options)
    
    assert any("fallback_key" == i.key for i in issues)
    assert "Deprecation: ar_semantic_qc invoked without paired canonical state" in caplog.text
