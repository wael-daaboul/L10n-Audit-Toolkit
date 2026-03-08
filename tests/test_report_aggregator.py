from pathlib import Path

from core.audit_report_utils import load_all_report_issues
from core.audit_runtime import read_simple_xlsx
from reports.report_aggregator import build_review_queue

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


def test_report_aggregator_builds_review_queue_and_hides_auto_safe(tmp_path: Path) -> None:
    results = tmp_path / "Results"
    write_json(
        results / "per_tool" / "localization" / "localization_audit_pro.json",
        {"findings": [{"key": "welcome", "issue_type": "confirmed_missing_key", "message": "Missing", "locale": "ar"}]},
    )
    issues = load_all_report_issues(results)[1]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"welcome": "Welcome"})
    write_json(runtime.ar_file, {})

    rows = build_review_queue(issues, runtime)
    assert rows == [
        {
            "key": "welcome",
            "locale": "ar",
            "old_value": "",
            "issue_type": "confirmed_missing_key",
            "suggested_fix": "Welcome",
            "approved_new": "",
            "status": "pending",
            "notes": "Missing",
            "context_type": "",
            "context_flags": "",
            "semantic_risk": "",
            "lt_signals": "",
            "review_reason": "",
        }
    ]


def test_simple_xlsx_reader_round_trips(tmp_path: Path) -> None:
    from core.audit_runtime import write_simple_xlsx

    path = tmp_path / "queue.xlsx"
    rows = [{"key": "a", "status": "pending"}, {"key": "b", "status": "approved"}]
    write_simple_xlsx(rows, ["key", "status"], path, sheet_name="Queue")

    assert read_simple_xlsx(path) == rows
