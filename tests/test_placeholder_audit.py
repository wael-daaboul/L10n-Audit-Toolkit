from pathlib import Path

from conftest import load_json, run_module


def run_placeholder_case(tmp_path: Path, fixtures_dir: Path, case: str) -> dict:
    out_json = tmp_path / f"{case}.json"
    run_module(
        "audits.placeholder_audit",
        [
            "--en", str(fixtures_dir / "locale_samples" / f"{case}.en.json"),
            "--ar", str(fixtures_dir / "locale_samples" / f"{case}.ar.json"),
            "--out-json", str(out_json),
            "--out-csv", str(tmp_path / f"{case}.csv"),
            "--out-xlsx", str(tmp_path / f"{case}.xlsx"),
        ],
    )
    return load_json(out_json)


def test_placeholder_valid_pair(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_placeholder_case(tmp_path, fixtures_dir, "placeholder_valid")
    assert payload["summary"]["findings"] == 0


def test_placeholder_missing_detected(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_placeholder_case(tmp_path, fixtures_dir, "placeholder_missing")
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "missing_in_ar" in issue_types


def test_placeholder_renamed_detected(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_placeholder_case(tmp_path, fixtures_dir, "placeholder_renamed")
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "renamed_placeholder" in issue_types


def test_placeholder_count_mismatch_detected(tmp_path: Path, fixtures_dir: Path) -> None:
    payload = run_placeholder_case(tmp_path, fixtures_dir, "placeholder_count")
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "missing_in_ar" in issue_types or "count_mismatch" in issue_types
