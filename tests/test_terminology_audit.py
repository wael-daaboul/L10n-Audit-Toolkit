from pathlib import Path

from conftest import load_json, run_module


def test_terminology_audit_detects_forbidden_terms(tmp_path: Path, fixtures_dir: Path) -> None:
    out_json = tmp_path / "terminology.json"
    run_module(
        "audits.terminology_audit",
        [
            "--en", str(fixtures_dir / "locale_samples" / "terminology.en.json"),
            "--ar", str(fixtures_dir / "locale_samples" / "terminology.ar.json"),
            "--glossary", str(fixtures_dir / "glossary" / "valid_glossary.json"),
            "--out-json", str(out_json),
        ],
    )
    payload = load_json(out_json)
    issue_types = {item["violation_type"] for item in payload["violations"]}
    assert "terminology_violation" in issue_types or "forbidden_term" in issue_types
