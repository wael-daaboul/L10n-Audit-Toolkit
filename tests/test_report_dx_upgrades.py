import pytest
from pathlib import Path
from l10n_audit.reports.report_aggregator import build_review_queue, render_markdown
from conftest import write_json

def test_aggregator_filters_info_from_review_queue(tmp_path):
    issues = [
        {"key": "crit", "severity": "critical", "message": "Critical issue", "source": "s1", "issue_type": "t1", "suggested_fix": "v1_fixed"},
        {"key": "info", "severity": "info", "message": "Info issue", "source": "s1", "issue_type": "t2"},
    ]
    runtime = type("RT", (), {
        "en_file": tmp_path/"en.json", 
        "ar_file": tmp_path/"ar.json", 
        "source_locale": "en", 
        "target_locales": ["ar"],
        "locale_format": "json"
    })()
    write_json(runtime.en_file, {"crit": "v1", "info": "v2"})
    write_json(runtime.ar_file, {"crit": "v1", "info": "v2"})

    rows = build_review_queue(issues, runtime)
    # Assert k2 (info) is missing
    assert len(rows) == 1
    assert rows[0]["key"] == "crit"

def test_aggregator_filters_info_from_markdown(tmp_path):
    issues = [
        {"key": "crit", "severity": "critical", "message": "Critical issue", "source": "s1", "issue_type": "t1"},
        {"key": "info", "severity": "info", "message": "Info issue", "source": "s1", "issue_type": "t2"},
    ]
    summary = {"total_issues": 2}
    safe_fixes = {"available": 0}
    review_rows = [{"key": "crit"}]
    source_status = {"s1": "2 issues"}
    
    md = render_markdown(issues, summary, safe_fixes, review_rows, source_status, [])
    
    assert "[CRITICAL] `crit`" in md
    assert "[INFO] `info`" not in md

def test_aggregator_deduplicates_by_key(tmp_path):
    issues = [
        {"key": "dup", "severity": "high", "message": "Mixed script", "source": "ar_locale_qc", "issue_type": "mixed_script", "suggested_fix": "فکس 1"},
        {"key": "dup", "severity": "medium", "message": "Meaning loss", "source": "ar_semantic_qc", "issue_type": "possible_meaning_loss", "suggested_fix": "فکس 2"},
    ]
    runtime = type("RT", (), {
        "en_file": tmp_path/"en.json", 
        "ar_file": tmp_path/"ar.json", 
        "source_locale": "en", 
        "target_locales": ["ar"],
        "locale_format": "json"
    })()
    write_json(runtime.en_file, {"dup": "Brand Help"})
    write_json(runtime.ar_file, {"dup": "مساعدة Brand"})

    rows = build_review_queue(issues, runtime)
    
    # Assert only 1 row for 'dup'
    assert len(rows) == 1
    row = rows[0]
    assert row["key"] == "dup"
    # Concatenated issue types
    assert "mixed_script" in row["issue_type"]
    assert "possible_meaning_loss" in row["issue_type"]
    # Concatenated notes
    assert "Mixed script" in row["notes"]
    assert "Meaning loss" in row["notes"]
    # But total issues should still reflect reality?
    # Actually, if we filter it from the high-level report, maybe we should also filter the count?
    # User said: "filter out low-priority noise... from high-level reports".
    # Usually "Total issues" should match what's visible.
    # But they said "Keep ALL issues in the raw l10n_issues.json".
    # If the MD says "Total issues: 2" but only 1 is listed, it might be confusing.
    # Let's see.

def test_aggregator_ignores_missing_reports_not_in_sources(tmp_path):
    from l10n_audit.core.audit_report_utils import load_all_report_issues
    results = tmp_path / "Results"
    results.mkdir()
    (results / "per_tool" / "localization").mkdir(parents=True)
    write_json(results / "per_tool" / "localization" / "localization_audit_pro.json", {"findings": []})
    
    # Specify only localization as source
    _reports, _issues, missing = load_all_report_issues(results, include_sources={"localization"})
    
    # Should NOT contain 'locale_qc' even though it's in standard MAP and missing from disk
    missing_sources = [m for m in missing]
    assert not any("en_locale_qc" in m for m in missing_sources)
