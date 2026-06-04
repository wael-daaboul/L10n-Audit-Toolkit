import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.audits.camel_validation import run_stage
from l10n_audit.models import AuditOptions

def test_camel_validation_stage_runs(tmp_path: Path):
    """
    Verify that camel_validation stage operates successfully on injected canonical state
    and correctly flags mixed scripts and unknown tokens (via pure-Python fallback or real backend).
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    
    # Ensure config and glossary exist to avoid file errors
    (tmp_path / "config.json").write_text("{}")

    options = MagicMock()
    options.write_reports = False

    # Injected data:
    # "valid_arabic": pure Arabic
    # "mixed_script": mixed Arabic and English
    canonical_ar_data = {
        "valid_arabic": "مرحبا بك في تطبيقنا",
        "mixed_script_key": "مرحبا user في تطبيقنا"
    }

    issues = run_stage(runtime, options, en_data={}, ar_data=canonical_ar_data)
    
    assert isinstance(issues, list)
    # The mixed script key must be flagged
    assert any(i.key == "mixed_script_key" for i in issues)
    
    # Verify the issue contents
    mixed_issue = [i for i in issues if i.key == "mixed_script_key"][0]
    assert mixed_issue.issue_type == "camel_mixed_script"
    assert mixed_issue.code == "AR_QC"
    assert mixed_issue.locale == "ar"
    assert mixed_issue.severity == "info"

def test_camel_validation_fallback_loading(tmp_path: Path, caplog):
    """
    Ensure camel_validation fallback works when paired state is missing, loading ar_file.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.locale_format = "json"
    
    # Set up files
    runtime.ar_file.write_text('{"mixed_key": "أهلا user"}')
    (tmp_path / "config.json").write_text("{}")
    
    options = MagicMock()
    options.write_reports = False

    issues = run_stage(runtime, options)
    
    assert any(i.key == "mixed_key" for i in issues)
    assert "camel_validation invoked without paired canonical state" in caplog.text


def test_camel_validation_severity_info(tmp_path: Path):
    """
    Verify camel_unknown_token and camel_mixed_script severities are info.
    """
    runtime = MagicMock()
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    
    (tmp_path / "config.json").write_text("{}")
    options = MagicMock()
    options.write_reports = False

    canonical_ar_data = {
        "mixed_key": "مرحبا user",
        "unknown_key": "مرحبا بك xyz",
    }

    def mock_analyze(text, enable_dialect=False):
        if "user" in text:
            return {"camel_mixed_script": "yes"}
        if "xyz" in text:
            return {"camel_unknown_count": "1", "camel_unknown_tokens": "xyz"}
        return {}

    with patch("l10n_audit.audits.camel_validation.analyze_arabic_text", side_effect=mock_analyze):
        issues = run_stage(runtime, options, en_data={}, ar_data=canonical_ar_data)
        
    assert len(issues) == 2
    issue_map = {i.key: i for i in issues}
    
    assert issue_map["mixed_key"].issue_type == "camel_mixed_script"
    assert issue_map["mixed_key"].severity == "info"
    
    assert issue_map["unknown_key"].issue_type == "camel_unknown_token"
    assert issue_map["unknown_key"].severity == "info"


def test_camel_validation_suppression_and_no_duplicates():
    """
    Verify camel findings are excluded from review_queue.xlsx but present in review_machine_queue.json,
    and running them does not create duplicate rows for the same key.
    """
    from l10n_audit.reports.report_aggregator import build_review_queue, build_human_review_queue
    
    runtime = MagicMock()
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.en_file = "en.json"
    runtime.ar_file = "ar.json"
    
    # 1. Pure camel_validation findings should be in build_review_queue (for review_machine_queue.json)
    # but suppressed in build_human_review_queue (for review_queue.xlsx)
    issues = [
        {
            "source": "camel_validation",
            "key": "welcome_key",
            "locale": "ar",
            "issue_type": "camel_mixed_script",
            "severity": "info",
            "detected_value": "مرحبا user",
            "message": "Mixed script camel",
        }
    ]
    
    with patch("l10n_audit.reports.report_aggregator.load_locale_mapping") as mock_load:
        mock_load.return_value = {"welcome_key": "مرحبا user"}
        review_rows = build_review_queue(issues, runtime)
        
    assert len(review_rows) == 1
    assert review_rows[0]["key"] == "welcome_key"
    assert review_rows[0]["issue_type"] == "camel_mixed_script"
    
    # In human queue, it must be suppressed (empty list)
    human_rows = build_human_review_queue(review_rows)
    assert len(human_rows) == 0

    # 2. Merged/Deduplicated scenario: ar_locale_qc (mixed_script) + camel_validation (camel_mixed_script)
    issues_merged = [
        {
            "source": "ar_locale_qc",
            "key": "welcome_key",
            "locale": "ar",
            "issue_type": "mixed_script",
            "severity": "medium",
            "detected_value": "مرحبا user",
            "message": "Mixed script",
        },
        {
            "source": "camel_validation",
            "key": "welcome_key",
            "locale": "ar",
            "issue_type": "camel_mixed_script",
            "severity": "info",
            "detected_value": "مرحبا user",
            "message": "Mixed script camel",
        }
    ]
    
    with patch("l10n_audit.reports.report_aggregator.load_locale_mapping") as mock_load:
        mock_load.return_value = {"welcome_key": "مرحبا user"}
        review_rows_merged = build_review_queue(issues_merged, runtime)
        
    # Must merge into a single row, no duplicates
    assert len(review_rows_merged) == 1
    assert review_rows_merged[0]["key"] == "welcome_key"
    assert "mixed_script" in review_rows_merged[0]["issue_type"]
    assert "camel_mixed_script" in review_rows_merged[0]["issue_type"]
    
    # In human queue, because it's merged and contains 'mixed_script', it is NOT suppressed,
    # and there is exactly one row (no duplicates).
    human_rows_merged = build_human_review_queue(review_rows_merged)
    assert len(human_rows_merged) == 1
    assert human_rows_merged[0]["key"] == "welcome_key"
