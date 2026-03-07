from pathlib import Path

from conftest import load_json, run_module


def test_ar_locale_qc_detects_targeted_issues(tmp_path: Path, fixtures_dir: Path) -> None:
    out_json = tmp_path / "ar_qc.json"
    run_module(
        "audits.ar_locale_qc",
        [
            "--en", str(fixtures_dir / "locale_samples" / "ar_qc.en.json"),
            "--input", str(fixtures_dir / "locale_samples" / "ar_qc.ar.json"),
            "--glossary", str(fixtures_dir / "glossary" / "valid_glossary.json"),
            "--out-json", str(out_json),
            "--out-csv", str(tmp_path / "ar_qc.csv"),
            "--out-xlsx", str(tmp_path / "ar_qc.xlsx"),
        ],
    )
    payload = load_json(out_json)
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "whitespace" in issue_types
    assert "slash_spacing" in issue_types
    assert "forbidden_term" in issue_types
    assert "suspicious_literal_translation" in issue_types
    assert "long_ui_string" in issue_types
