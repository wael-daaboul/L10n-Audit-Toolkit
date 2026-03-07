from pathlib import Path

import pytest

from audits.placeholder_audit import compare_placeholders
from core.audit_runtime import AuditRuntimeError
from core.locale_loaders import load_locale_mapping
from core.usage_scanner import compile_usage_patterns, scan_code_keys


def test_laravel_php_loader_flattens_grouped_keys(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "valid" / "en"
    payload = load_locale_mapping(en_dir, locale_format="laravel_php")

    assert payload["messages.login"] == "Login"
    assert payload["messages.auth.failed"] == "These credentials do not match our records."
    assert payload["validation.required"] == "The :attribute field is required."
    assert payload["messages.trips"].startswith("{count, plural,")


def test_laravel_php_loader_rejects_unsupported_constructs(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "unsupported" / "en"
    with pytest.raises(AuditRuntimeError):
        load_locale_mapping(en_dir, locale_format="laravel_php")


def test_laravel_php_placeholder_logic_works_on_normalized_mapping(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "placeholder_mismatch" / "en"
    ar_dir = fixtures_dir / "laravel_php" / "placeholder_mismatch" / "ar"
    en_data = load_locale_mapping(en_dir, locale_format="laravel_php")
    ar_data = load_locale_mapping(ar_dir, locale_format="laravel_php")

    findings = compare_placeholders("messages.summary", str(en_data["messages.summary"]), str(ar_data["messages.summary"]))
    issue_types = {item["issue_type"] for item in findings}
    assert "renamed_placeholder" in issue_types


def test_laravel_php_loader_ignores_comments_and_docblocks(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "commented" / "en"
    ar_dir = fixtures_dir / "laravel_php" / "commented" / "ar"

    en_data = load_locale_mapping(en_dir, locale_format="laravel_php")
    ar_data = load_locale_mapping(ar_dir, locale_format="laravel_php")

    assert en_data["lang.intro_link"] == "Open intro"
    assert en_data["lang.auth.failed"] == "These credentials do not match our records."
    assert en_data["lang.cta.description"] == "Continue to the CTA tab."
    assert ar_data["lang.intro_link"] == "افتح المقدمة"
    assert ar_data["lang.auth.failed"] == "بيانات الاعتماد هذه لا تطابق سجلاتنا."


def test_laravel_php_loader_supports_classic_array_syntax(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "classic" / "en"
    ar_dir = fixtures_dir / "laravel_php" / "classic" / "ar"

    en_data = load_locale_mapping(en_dir, locale_format="laravel_php")
    ar_data = load_locale_mapping(ar_dir, locale_format="laravel_php")

    assert en_data["lang.* Generate the link for the Intro section button from the CTA tab."] == "* Generate the link for the Intro section button from the CTA tab."
    assert en_data["lang.--Select_Employee_Role--"] == "--Select Employee Role--"
    assert en_data["lang.auth.failed"] == "These credentials do not match our records."
    assert ar_data["lang.auth.failed"] == "بيانات الاعتماد هذه لا تطابق سجلاتنا."


def test_laravel_php_loader_supports_mixed_short_and_classic_arrays(fixtures_dir: Path) -> None:
    en_dir = fixtures_dir / "laravel_php" / "mixed_arrays" / "en"
    ar_dir = fixtures_dir / "laravel_php" / "mixed_arrays" / "ar"

    en_data = load_locale_mapping(en_dir, locale_format="laravel_php")
    ar_data = load_locale_mapping(ar_dir, locale_format="laravel_php")

    assert en_data["lang.outer.inner.label"] == "Open intro"
    assert en_data["lang.cta.description.text"] == "Continue to the CTA tab."
    assert ar_data["lang.outer.inner.label"] == "افتح المقدمة"
    assert ar_data["lang.cta.description.text"] == "تابع إلى تبويب الإجراء."


def test_laravel_php_grouped_keys_align_with_usage_scanner(tmp_path: Path) -> None:
    code_dir = tmp_path / "app"
    code_dir.mkdir()
    (code_dir / "controller.php").write_text(
        "__('messages.login'); trans('validation.required'); @lang('messages.auth.failed');",
        encoding="utf-8",
    )

    compiled = compile_usage_patterns(
        ["laravel_trans_helper", "laravel_lang_directive", "laravel_trans_function"]
    )
    occurrences = scan_code_keys([code_dir], compiled, [".php"], key_filter={"messages.login", "validation.required", "messages.auth.failed"})

    assert "messages.login" in occurrences
    assert "validation.required" in occurrences
    assert "messages.auth.failed" in occurrences
