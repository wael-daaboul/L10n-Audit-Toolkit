from pathlib import Path

from conftest import load_json, run_module


def test_localization_audit_pro_emits_usage_metadata(tmp_path: Path, tools_dir: Path) -> None:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    code_dir = tmp_path / "src"
    out_json = tmp_path / "localization.json"

    code_dir.mkdir()
    en_file.write_text('{"profile.helper":"Save your profile to continue."}', encoding="utf-8")
    ar_file.write_text('{"profile.helper":"احفظ ملفك الشخصي للمتابعة."}', encoding="utf-8")
    (code_dir / "screen.dart").write_text("TextFormField(helperText: 'profile.helper'.tr)\n", encoding="utf-8")

    run_module(
        "l10n_audit.audits.l10n_audit_pro",
        [
            "--en",
            str(en_file),
            "--ar",
            str(ar_file),
            "--code",
            str(code_dir),
            "--out-json",
            str(out_json),
            "--out-en",
            str(tmp_path / "localization_en.md"),
            "--out-ar",
            str(tmp_path / "localization_ar.md"),
        ],
        cwd=tools_dir,
    )

    payload = load_json(out_json)
    assert payload["usage_contexts"]["profile.helper"] == ["helper_text"]
    assert payload["usage_metadata"]["profile.helper"]["ui_surfaces"] == ["form"]
    assert payload["usage_metadata"]["profile.helper"]["text_roles"] == ["message"]
