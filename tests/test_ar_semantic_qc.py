import json
import pytest
from pathlib import Path

from conftest import load_json, run_module


def test_ar_semantic_qc_generates_review_candidate_for_missing_action(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    out_json = tmp_path / "ar_semantic.json"

    en_file.write_text('{"save_profile_helper":"Save your profile to continue."}', encoding="utf-8")
    ar_file.write_text('{"save_profile_helper":"الملف الشخصي للمتابعة"}', encoding="utf-8")

    run_module(
        "l10n_audit.audits.ar_semantic_qc",
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


def test_ar_semantic_qc_keeps_context_sensitive_role_pairs_review_only(tmp_path: Path, tools_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    out_json = tmp_path / "ar_semantic_context.json"
    config_file = tmp_path / "test_config.json"

    en_file.write_text('{"add_vehicle_details":"Add vehicle details to send approval request to admin."}', encoding="utf-8")
    ar_file.write_text('{"add_vehicle_details":"أضف بيانات المركبة لإرسال طلب الموافقة إلى الإدارة."}', encoding="utf-8")
    config_file.write_text(json.dumps({
        "project_profile": "flutter_getx_json",
        "project_root": str(tools_dir),
        "entity_whitelist": {
            "en": ["admin"],
            "ar": ["الإدارة"]
        }
    }))
    monkeypatch.setenv("L10N_AUDIT_CONFIG", str(config_file))

    run_module(
        "l10n_audit.audits.ar_semantic_qc",
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


# ---------------------------------------------------------------------------
# Fix 1.2: disable multi-action synthesis
# ---------------------------------------------------------------------------

def test_fix1_2_multi_action_returns_empty_candidate() -> None:
    """build_semantic_candidate must return ('', 'low') for multi-action bundles."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:save", "missing_action:send"]}
    candidate, confidence = build_semantic_candidate(
        "Save and send the document.", "المستند", bundle
    )
    assert candidate == ""
    assert confidence == "low"


# ---------------------------------------------------------------------------
# Fix 1.4: disable synthesis for status/informational Arabic strings
# ---------------------------------------------------------------------------

def test_fix1_4_status_string_returns_empty_candidate() -> None:
    """build_semantic_candidate must return ('', 'low') for status-like Arabic text."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:add"]}
    candidate, confidence = build_semantic_candidate(
        "Add the item.", "تم حذف العنوان بنجاح", bundle
    )
    assert candidate == ""
    assert confidence == "low"


def test_fix1_4_failure_string_returns_empty_candidate() -> None:
    """Failure-indicator strings must also be suppressed (Fix 1.4)."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:send"]}
    candidate, confidence = build_semantic_candidate(
        "Send the message.", "فشل إرسال الرسالة", bundle
    )
    assert candidate == ""
    assert confidence == "low"


def test_fix1_4_plain_label_still_generates_candidate() -> None:
    """A plain action label must still produce a candidate after Fix 1.4."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:save"]}
    candidate, confidence = build_semantic_candidate(
        "Save profile.", "الملف الشخصي", bundle
    )
    assert candidate.startswith("احفظ")
    assert confidence == "medium"


# ---------------------------------------------------------------------------
# Fix 2.3: punctuation hardening
# ---------------------------------------------------------------------------

def test_fix2_3_no_double_period() -> None:
    """Candidate must not end with '..' when ar_text already ends with '.' (Fix 2.3)."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:save"]}
    candidate, _ = build_semantic_candidate(
        "Save your profile to continue.", "الملف الشخصي للمتابعة.", bundle
    )
    assert not candidate.endswith("..")


def test_fix2_3_arabic_comma_terminates_candidate() -> None:
    """Candidate must not append '.' when ar_text ends with '،' (Fix 2.3)."""
    from l10n_audit.audits.ar_semantic_qc import build_semantic_candidate

    bundle = {"semantic_flags": ["missing_action:save"]}
    candidate, _ = build_semantic_candidate(
        "Save your profile to continue.", "الملف الشخصي،", bundle
    )
    assert not candidate.endswith("،.")
