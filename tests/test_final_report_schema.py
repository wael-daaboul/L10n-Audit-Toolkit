from pathlib import Path

from conftest import load_json, validate_schema


def test_fixture_final_report_matches_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "reports" / "final_audit_report.valid.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "final_audit_report.schema.json")
    assert errors == []


def test_invalid_final_report_fails_schema(tools_dir: Path) -> None:
    payload = {"summary": {}, "issues": []}
    errors = validate_schema(payload, tools_dir / "schemas" / "final_audit_report.schema.json")
    assert errors
