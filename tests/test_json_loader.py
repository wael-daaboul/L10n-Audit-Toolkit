from pathlib import Path

import pytest

from core.audit_runtime import AuditRuntimeError
from core.locale_loaders import load_locale_mapping


def test_json_loader_flattens_nested_objects(tmp_path: Path) -> None:
    locale_file = tmp_path / "ar.json"
    locale_file.write_text(
        '{"home":{"title":"الرئيسية","cta":{"save":"حفظ"}},"feature.enabled":true,"count":3}',
        encoding="utf-8",
    )

    payload = load_locale_mapping(locale_file, locale_format="json")

    assert payload == {
        "home.title": "الرئيسية",
        "home.cta.save": "حفظ",
        "feature.enabled": True,
        "count": 3,
    }


def test_json_loader_rejects_structural_collisions(tmp_path: Path) -> None:
    locale_file = tmp_path / "en.json"
    locale_file.write_text('{"home":"Home","home.title":"Title"}', encoding="utf-8")

    with pytest.raises(AuditRuntimeError):
        load_locale_mapping(locale_file, locale_format="json")


def test_json_loader_rejects_non_object_roots(tmp_path: Path) -> None:
    locale_file = tmp_path / "invalid.json"
    locale_file.write_text('["Home"]', encoding="utf-8")

    with pytest.raises(AuditRuntimeError):
        load_locale_mapping(locale_file, locale_format="json")
