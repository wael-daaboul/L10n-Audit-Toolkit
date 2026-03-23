from pathlib import Path

from conftest import load_json, run_module


def run_icu_case(tmp_path: Path, fixtures_dir: Path, case: str) -> dict:
    out_json = tmp_path / f"{case}.json"
    run_module(
        "l10n_audit.audits.icu_message_audit",
        [
            "--en", str(fixtures_dir / "locale_samples" / f"{case}.en.json"),
            "--ar", str(fixtures_dir / "locale_samples" / f"{case}.ar.json"),
            "--out-json", str(out_json),
            "--out-csv", str(tmp_path / f"{case}.csv"),
            "--out-xlsx", str(tmp_path / f"{case}.xlsx"),
        ],
    )
    return load_json(out_json)


def test_valid_icu_messages_pass(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_icu_case(tmp_path, fixtures_dir, "icu_valid")
    assert payload["summary"]["findings"] == 0


def test_invalid_icu_messages_report_structure_errors(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_icu_case(tmp_path, fixtures_dir, "icu_invalid")
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "icu_branch_incomplete" in issue_types
    assert "icu_literal_text_only" in issue_types or "icu_branch_mismatch" in issue_types
    assert "icu_placeholder_mismatch" in issue_types or "icu_branch_mismatch" in issue_types
