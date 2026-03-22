import json
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
    assert "forbidden_term" in issue_types or "context_sensitive_term_conflict" in issue_types
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


def test_ar_locale_qc_skips_punctuation_rewrite_for_technical_mixed_text(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    glossary_file = tmp_path / "glossary.json"
    out_json = tmp_path / "ar_qc_technical.json"

    en_file.write_text('{"link":"Open الرابط https://api.example.com/v1/login?user=${user}"}', encoding="utf-8")
    ar_file.write_text('{"link":"افتح الرابط https://api.example.com/v1/login?user=${user} ؟"}', encoding="utf-8")
    glossary_file.write_text('{"terms":[],"rules":{"forbidden_terms":[]}}', encoding="utf-8")

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
            str(tmp_path / "ar_qc_technical.csv"),
            "--out-xlsx",
            str(tmp_path / "ar_qc_technical.xlsx"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    assert "english_punctuation" not in {item["issue_type"] for item in payload["findings"]}


def test_ar_locale_qc_flags_sentence_shape_and_meaning_loss(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    glossary_file = tmp_path / "glossary.json"
    out_json = tmp_path / "ar_qc_sentence.json"

    en_file.write_text('{"save_profile_helper":"Save your profile to continue."}', encoding="utf-8")
    ar_file.write_text('{"save_profile_helper":"الملف الشخصي للمتابعة"}', encoding="utf-8")
    glossary_file.write_text('{"terms":[],"rules":{"forbidden_terms":[]}}', encoding="utf-8")

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
            str(tmp_path / "ar_qc_sentence.csv"),
            "--out-xlsx",
            str(tmp_path / "ar_qc_sentence.xlsx"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    issue_types = {item["issue_type"] for item in payload["findings"]}
    assert "sentence_shape_mismatch" in issue_types
    assert "possible_meaning_loss" in issue_types
    finding = next(item for item in payload["findings"] if item["issue_type"] == "possible_meaning_loss")
    assert finding["fix_mode"] == "review_required"
    assert finding["text_role"] == "message"


def test_ar_locale_qc_protects_placeholders_and_numbers(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    glossary_file = tmp_path / "glossary.json"
    out_json = tmp_path / "ar_qc_protection.json"

    # 1. Arabic punctuation spacing around placeholders
    # 2. English number format preservation (1,000)
    # 3. Multiple placeholders
    data = {
        "welcome": "مرحباً {name} ، كيف حالك ؟",
        "price": "السعر هو 1,000 ريال",
        "update": "تم التحديث : {{count}}",
    }
    en_file.write_text('{"welcome":"Welcome {name}, how are you?", "price":"Price is 1,000", "update":"Updated: {{count}}"}', encoding="utf-8")
    ar_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    glossary_file.write_text('{"terms":[],"rules":{"forbidden_terms":[]}}', encoding="utf-8")

    run_module(
        "audits.ar_locale_qc",
        [
            "--en", str(en_file),
            "--input", str(ar_file),
            "--glossary", str(glossary_file),
            "--out-json", str(out_json),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    findings = payload["findings"]
    
    # "welcome" should have punctuation fixed but {name} preserved
    welcome_f = next(f for f in findings if f["key"] == "welcome" and f["issue_type"] == "punctuation_spacing")
    assert welcome_f["new"] == "مرحباً {name}، كيف حالك؟"
    
    # "price" should NOT have punctuation findings for the number
    price_findings = [f for f in findings if f["key"] == "price" and f["issue_type"] == "english_punctuation"]
    assert len(price_findings) == 0
    
    # "update" should have punctuation fixed but {{count}} preserved
    update_f = next(f for f in findings if f["key"] == "update" and f["issue_type"] == "punctuation_spacing")
    assert update_f["new"] == "تم التحديث: {{count}}"
