from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import AuditRuntimeError
from l10n_audit.core.locale_exporters import export_locale_mapping
from l10n_audit.core.locale_loaders import load_locale_mapping


def test_laravel_php_exporter_writes_grouped_files_and_nested_arrays(tmp_path: Path) -> None:
    mapping = {
        "lang.Add": "Add",
        "validation.required": "The :attribute field is required.",
        "messages.auth.failed": "These credentials do not match our records.",
        "messages.auth.locked": "Account is locked.",
    }

    out_dir = tmp_path / "exports" / "en"
    paths = export_locale_mapping(mapping, "laravel_php", out_dir)
    exported = {path.name for path in paths}

    assert exported == {"lang.php", "messages.php", "validation.php"}
    messages = (out_dir / "messages.php").read_text(encoding="utf-8")
    assert "'auth' => [" in messages
    assert "'failed' => 'These credentials do not match our records.'" in messages
    assert "'locked' => 'Account is locked.'" in messages


def test_laravel_php_exporter_round_trips_with_loader(tmp_path: Path) -> None:
    en_mapping = {
        "lang.Add": "Add",
        "messages.auth.failed": "These credentials do not match our records.",
        "validation.required": "The :attribute field is required.",
    }
    ar_mapping = {
        "lang.Add": "إضافة",
        "messages.auth.failed": "بيانات الاعتماد هذه لا تطابق سجلاتنا.",
        "validation.required": "حقل :attribute مطلوب.",
    }

    en_dir = tmp_path / "exports" / "en"
    ar_dir = tmp_path / "exports" / "ar"
    export_locale_mapping(en_mapping, "laravel_php", en_dir)
    export_locale_mapping(ar_mapping, "laravel_php", ar_dir)

    loaded_en = load_locale_mapping(en_dir, locale_format="laravel_php")
    loaded_ar = load_locale_mapping(ar_dir, locale_format="laravel_php")

    assert loaded_en == en_mapping
    assert loaded_ar == ar_mapping


def test_json_exporter_writes_safe_generated_json(tmp_path: Path) -> None:
    mapping = {"home.title": "Home", "common.save": "Save"}
    out_file = tmp_path / "exports" / "en.json"
    paths = export_locale_mapping(mapping, "json", out_file)

    assert paths == [out_file]
    loaded = load_locale_mapping(out_file, locale_format="json")
    assert loaded == mapping


def test_json_exporter_preserves_original_key_order(tmp_path: Path) -> None:
    mapping = {"z.last": "Last", "a.first": "First", "m.middle": "Middle"}
    out_file = tmp_path / "exports" / "ordered.json"
    export_locale_mapping(mapping, "json", out_file)
    content = out_file.read_text(encoding="utf-8")
    assert content.index('"z.last"') < content.index('"a.first"') < content.index('"m.middle"')


def test_laravel_php_exporter_warns_on_structural_collision(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    mapping = {"messages.a": "Value", "messages.a.b": "Nested"}
    out_dir = tmp_path / "exports" / "en"
    export_locale_mapping(mapping, "laravel_php", out_dir)
    
    assert "Structural collision" in caplog.text
    content = (out_dir / "messages.php").read_text(encoding="utf-8")
    assert "'a' => 'Value'" in content
    assert "'a.b' => 'Nested'" in content
