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


def test_ar_locale_qc_blocks_context_sensitive_admin_rewrite(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    glossary_file = tmp_path / "glossary.json"
    out_json = tmp_path / "ar_qc_context.json"

    en_file.write_text('{"add_vehicle_details":"Add vehicle details to send approval request to admin."}', encoding="utf-8")
    ar_file.write_text('{"add_vehicle_details":"أضف بيانات المركبة لإرسال طلب الموافقة إلى الإدارة."}', encoding="utf-8")
    glossary_file.write_text(
        '{"terms":[{"term_en":"admin","approved_ar":"المدير","forbidden_ar":["الإدارة"]}],"rules":{"forbidden_terms":[]}}',
        encoding="utf-8",
    )

    run_module(
        "audits.ar_locale_qc",
        [
            "--en",
            str(en_file),
            "--input",
            str(ar_file),
            "--glossary",
            str(glossary_file),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(tmp_path / "ar_qc_context.csv"),
            "--out-xlsx",
            str(tmp_path / "ar_qc_context.xlsx"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    finding = next(item for item in payload["findings"] if item["issue_type"] == "context_sensitive_term_conflict")
    assert finding["fix_mode"] == "review_required"
    assert finding["new"] == ""
    assert finding["context_type"] == "helper_text"
    assert finding["semantic_risk"] == "high"
    assert "Possible role/entity ambiguity" in finding["review_reason"]
