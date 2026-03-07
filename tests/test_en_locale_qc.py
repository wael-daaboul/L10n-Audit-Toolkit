from pathlib import Path

from conftest import load_json, run_module


def test_en_locale_qc_detects_known_patterns(tmp_path: Path, fixtures_dir: Path) -> None:
    out_json = tmp_path / "en_qc.json"
    run_module(
        "audits.en_locale_qc",
        [
            "--input", str(fixtures_dir / "locale_samples" / "en_qc.en.json"),
            "--ar", str(fixtures_dir / "locale_samples" / "en_qc.ar.json"),
            "--out-json", str(out_json),
            "--out-csv", str(tmp_path / "en_qc.csv"),
            "--out-xlsx", str(tmp_path / "en_qc.xlsx"),
        ],
    )
    payload = load_json(out_json)
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "grammar" in issue_types
    assert "spacing" in issue_types
    assert "whitespace" in issue_types
    assert "ui_wording" in issue_types
