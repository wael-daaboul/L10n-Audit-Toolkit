from pathlib import Path

from audits.placeholder_audit import compare_placeholders
from core.audit_runtime import parse_placeholders
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


def test_placeholder_parser_supports_extended_tokens() -> None:
    items = parse_placeholders("Hello %@ %1$s $1 {0} {{username}} ${value} {user}")
    raws = [item["raw"] for item in items]
    assert "%@" in raws
    assert "%1$s" in raws
    assert "$1" in raws
    assert "{0}" in raws
    assert "{{username}}" in raws
    assert "${value}" in raws
    assert "{user}" in raws


def test_placeholder_parser_handles_icu_pound() -> None:
    items = parse_placeholders("{count, plural, one{# trip} other{# trips for %@}}")
    raws = [item["raw"] for item in items]
    assert "#" in raws
    assert "%@" in raws


def test_placeholder_order_mismatch_is_high_for_runtime_sensitive_styles() -> None:
    findings = compare_placeholders("trip", "%1$s then %2$s", "%2$s ثم %1$s")
    finding = next(item for item in findings if item["issue_type"] == "order_mismatch")
    assert finding["severity"] == "high"


def test_placeholder_parser_avoids_common_false_positives() -> None:
    items = parse_placeholders("https://api.example.com mailto:user@example.com 12:30 --flag: value")
    assert items == []
