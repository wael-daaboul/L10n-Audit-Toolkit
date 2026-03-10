from pathlib import Path

from conftest import load_json, run_module


def test_ar_semantic_qc_generates_review_candidate_for_missing_action(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    out_json = tmp_path / "ar_semantic.json"

    en_file.write_text('{"save_profile_helper":"Save your profile to continue."}', encoding="utf-8")
    ar_file.write_text('{"save_profile_helper":"الملف الشخصي للمتابعة"}', encoding="utf-8")

    run_module(
        "audits.ar_semantic_qc",
        [
            "--en",
            str(en_file),
            "--input",
            str(ar_file),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(tmp_path / "ar_semantic.csv"),
            "--out-xlsx",
            str(tmp_path / "ar_semantic.xlsx"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    finding = next(item for item in payload["findings"] if item["issue_type"] == "possible_meaning_loss")
    assert finding["fix_mode"] == "review_required"
    assert finding["candidate_value"].startswith("احفظ ")
    assert finding["suggestion_confidence"] == "medium"


def test_ar_semantic_qc_keeps_context_sensitive_role_pairs_review_only(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    out_json = tmp_path / "ar_semantic_context.json"

    en_file.write_text('{"add_vehicle_details":"Add vehicle details to send approval request to admin."}', encoding="utf-8")
    ar_file.write_text('{"add_vehicle_details":"أضف بيانات المركبة لإرسال طلب الموافقة إلى الإدارة."}', encoding="utf-8")

    run_module(
        "audits.ar_semantic_qc",
        [
            "--en",
            str(en_file),
            "--input",
            str(ar_file),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(tmp_path / "ar_semantic_context.csv"),
            "--out-xlsx",
            str(tmp_path / "ar_semantic_context.xlsx"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    finding = next(item for item in payload["findings"] if item["issue_type"] == "context_sensitive_meaning")
    assert finding["candidate_value"] == ""
    assert finding["fix_mode"] == "review_required"
