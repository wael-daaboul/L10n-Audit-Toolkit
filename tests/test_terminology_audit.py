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
    assert "hard_violation" in issue_types or "forbidden_term" in issue_types


def test_terminology_audit_blocks_context_sensitive_admin_replacement(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    glossary_file = tmp_path / "glossary.json"
    out_json = tmp_path / "terminology_context.json"

    en_file.write_text('{"add_vehicle_details":"Add vehicle details to send approval request to admin."}', encoding="utf-8")
    ar_file.write_text('{"add_vehicle_details":"أضف بيانات المركبة لإرسال طلب الموافقة إلى الإدارة."}', encoding="utf-8")
    glossary_file.write_text(
        '{"terms":[{"term_en":"admin","approved_ar":"المدير","forbidden_ar":["الإدارة"]}],"rules":{"forbidden_terms":[]}}',
        encoding="utf-8",
    )

    run_module(
        "audits.terminology_audit",
        [
            "--en",
            str(en_file),
            "--ar",
            str(ar_file),
            "--glossary",
            str(glossary_file),
            "--out-json",
            str(out_json),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    conflict = next(item for item in payload["violations"] if item["violation_type"] == "context_sensitive_term_conflict")
    assert conflict["expected_ar"] == ""
    assert conflict["fix_mode"] == "review_required"
    assert conflict["semantic_risk"] == "high"
