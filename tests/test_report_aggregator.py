from pathlib import Path

from core.audit_report_utils import load_all_report_issues

from conftest import write_json


def test_report_loader_merges_and_dedupes(tmp_path: Path) -> None:
    results = tmp_path / "Results"
    write_json(
        results / "per_tool" / "localization" / "localization_audit_pro.json",
        {"findings": [{"key": "x", "issue_type": "missing_in_ar", "message": "Missing", "locale": "ar"}]},
    )
    write_json(
        results / "per_tool" / "en_locale_qc" / "en_locale_qc_report.json",
        {
            "findings": [
                {"key": "trimmed", "issue_type": "whitespace", "severity": "low", "message": "Trim", "old": " x ", "new": "x"},
                {"key": "trimmed", "issue_type": "whitespace", "severity": "low", "message": "Trim", "old": " x ", "new": "x"},
            ]
        },
    )

    _reports, issues, missing = load_all_report_issues(results)
    assert len(issues) == 2
    assert missing
