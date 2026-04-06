
import pytest
import json
from pathlib import Path
from l10n_audit.reports.report_aggregator import build_review_queue, create_analytical_payload

def _runtime():
    return type("Runtime", (), {
        "en_file": "en.json", "ar_file": "ar.json", "locale_format": "json",
        "source_locale": "en", "target_locales": ("ar",),
        "results_dir": ".", "project_root": Path(".")
    })()

def test_phase11_real_reconciliation_path():
    # Proof of reconciling the REAL report-generation path against the final filtered queue.
    
    # 1. ACTIONABLE Safe fix
    i1 = {"key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
          "current_value": "Hello", "suggested_fix": "Hello.", "source": "ar_qc"}
    
    # 2. ACTIONABLE Review item (semantic)
    i2 = {"key": "k2", "locale": "ar", "issue_type": "meaning_loss", "severity": "high",
          "current_value": "Submit", "suggested_fix": "Finish", "source": "ar_qc"}
    
    # 3. ACTIONABLE Blocked item (safety)
    i3 = {"key": "k3", "locale": "ar", "issue_type": "brand", "severity": "critical",
          "current_value": "Bkash", "suggested_fix": "bkash", "source": "ar_qc"}
    
    # 4. SUPPRESSED NOISE (Trivial)
    i4 = {"key": "k4", "locale": "ar", "issue_type": "noise", "severity": "low",
          "current_value": "same", "suggested_fix": "same  ", "source": "ar_qc"}

    issues = [i1, i2, i3, i4]
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Hello", "k2": "Submit", "k3": "Bkash", "k4": "same"
        })
        
        # Step A: Generate filtered operational truth
        review_rows = build_review_queue(issues, _runtime())
        
        # Step B: Call REAL report path
        # Mocking auxiliary components for isolation
        reports = {"ar_qc": {}}
        missing = ["dummy.json"]
        summary_raw = {"total_issues": 4} # Pre-filtered
        safe_fixes_raw = {"available": 1}
        source_status = {"ar_qc": "ok"}
        
        payload = create_analytical_payload(
            review_rows=review_rows,
            issues=issues,
            reports=reports,
            missing=missing,
            summary=summary_raw,
            safe_fixes=safe_fixes_raw,
            source_status=source_status
        )
        
        # PROOF 1: Actionable Counts match strictly filtered Truth
        res_summary = payload["summary"]
        assert res_summary["total_issues"] == 3 # k4 excluded
        assert res_summary["critical_issues"] == 2 # k2, k3
        assert res_summary["safe_fixes_available"] == 1 # k1
        assert res_summary["review_required_issues"] == 2 # k2, k3
        assert res_summary["blocked_issues"] == 1 # k3
        
        # PROOF 2: Analytical Sections reconcile with Filtered rows
        # by_severity check
        assert res_summary["by_severity"]["critical"] == 1 # k3
        assert res_summary["by_severity"]["high"] == 1     # k2
        assert res_summary["by_severity"]["low"] == 1      # k1
        assert "noise" not in res_summary["by_issue_type"], "Suppressed noise leaked into buckets"
        
        # by_source check
        assert res_summary["by_source"]["ar_qc"] == 3
        
        # PROOF 3: Operational Queue Parity
        assert len(payload["review_queue"]) == 3
        assert payload["review_queue"] == review_rows

def test_final_report_section_stability():
    # Verify that the report payload preserves all required sections as per frozen contract
    mock_sum = {"total_issues": 0}
    mock_safe = {"available": 0}
    payload = create_analytical_payload([], [], {}, [], mock_sum, mock_safe, {})
    
    sections = [
        "summary", "missing_reports", "included_sources", "priority_order",
        "recommendations", "source_status", "review_queue", "issues"
    ]
    for section in sections:
        assert section in payload
    
    summary_sections = [
        "total_issues", "critical_issues", "safe_fixes_available",
        "review_required_issues", "blocked_issues",
        "by_severity", "by_source", "by_issue_type"
    ]
    for s in summary_sections:
        assert s in payload["summary"]
