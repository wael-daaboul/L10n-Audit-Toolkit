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


def test_en_locale_qc_skips_technical_strings(tmp_path: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    out_json = tmp_path / "en_technical.json"
    en_file.write_text(
        '{"npm":"npm install failed.","cd":"cd /usr/local/bin.","url":"https://api.example.com/v1/login","mail":"user@example.com","iphone":"iPhone connected."}',
        encoding="utf-8",
    )
    ar_file.write_text('{"npm":"","cd":"","url":"","mail":"","iphone":""}', encoding="utf-8")
    run_module(
        "audits.en_locale_qc",
        [
            "--input",
            str(en_file),
            "--ar",
            str(ar_file),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(tmp_path / "en_technical.csv"),
            "--out-xlsx",
            str(tmp_path / "en_technical.xlsx"),
        ],
    )
    payload = load_json(out_json)
    issue_types = {(item["key"], item["issue_type"]) for item in payload["findings"]}
    assert ("iphone", "capitalization") not in issue_types
    assert ("url", "capitalization") not in issue_types
