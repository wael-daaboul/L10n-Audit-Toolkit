from pathlib import Path

from core.audit_runtime import load_runtime
from core.usage_scanner import compile_usage_patterns, scan_code_keys, scan_code_usage


def test_runtime_loads_profile_defaults(monkeypatch, runtime_test_config: Path) -> None:
    monkeypatch.setenv("L10N_AUDIT_CONFIG", str(runtime_test_config))
    runtime = load_runtime("audits/l10n_audit_pro.py", validate=False)
    assert runtime.project_profile == "flutter_getx_json"
    assert runtime.locale_format == "json"
    assert runtime.source_locale == "en"
    assert runtime.target_locales == ("ar",)
    assert runtime.code_dirs
    assert runtime.usage_patterns


def test_usage_scanner_supports_multiple_framework_patterns(tmp_path: Path) -> None:
    code_dir = tmp_path / "code"
    code_dir.mkdir()
    (code_dir / "app.dart").write_text("'home.title'.tr\n", encoding="utf-8")
    (code_dir / "view.php").write_text("__('admin.dashboard'); @lang('users.title'); trans('alerts.saved');", encoding="utf-8")
    (code_dir / "page.tsx").write_text("t('common.save'); i18n.t('common.cancel');", encoding="utf-8")
    (code_dir / "component.vue").write_text("{{ $t('nav.home') }}", encoding="utf-8")

    compiled = compile_usage_patterns(
        [
            "flutter_getx_tr",
            "laravel_trans_helper",
            "laravel_lang_directive",
            "laravel_trans_function",
            "react_t_function",
            "react_i18n_t",
            "vue_t_function",
        ]
    )
    occurrences = scan_code_keys(
        [code_dir],
        compiled,
        [".dart", ".php", ".tsx", ".vue"],
    )

    assert "home.title" in occurrences
    assert "admin.dashboard" in occurrences
    assert "users.title" in occurrences
    assert "alerts.saved" in occurrences
    assert "common.save" in occurrences
    assert "common.cancel" in occurrences
    assert "nav.home" in occurrences


def test_laravel_custom_helper_static_and_dynamic_detection(tmp_path: Path) -> None:
    code_dir = tmp_path / "app"
    code_dir.mkdir()
    (code_dir / "helpers.php").write_text(
        "\n".join(
            [
                "translate('Add');",
                "translate(\"Contact Us\");",
                "translate(key: 'Home', locale: $locale);",
                "translate(",
                "    'hit count'",
                ");",
                "translate($key);",
                "translate(key: $notification['title'], locale: $user?->current_language_key);",
                "translate(TRIP_REQUEST_404['message']);",
            ]
        ),
        encoding="utf-8",
    )

    usage = scan_code_usage(
        [code_dir],
        ["laravel_custom_translate_static"],
        [".php"],
        profile="laravel_php",
        locale_format="laravel_php",
        locale_keys={"lang.Add", "lang.Contact Us", "lang.Home", "lang.hit count"},
    )

    assert set(usage["static_occurrences"]) == {"lang.Add", "lang.Contact Us", "lang.Home", "lang.hit count"}
    assert usage["dynamic_usage_count"] == 3
    assert usage["dynamic_breakdown"]["laravel_custom_translate_dynamic"] == 3


def test_laravel_native_static_and_dynamic_detection(tmp_path: Path) -> None:
    code_dir = tmp_path / "views"
    code_dir.mkdir()
    (code_dir / "page.blade.php").write_text(
        "\n".join(
            [
                "{{ __('lang.Add') }}",
                "@lang('validation.required')",
                "<?php trans(",
                "  \"messages.saved\"",
                "); ?>",
                "{{ __($key) }}",
                "{{ trans($value) }}",
                "@lang($messageKey)",
            ]
        ),
        encoding="utf-8",
    )

    usage = scan_code_usage(
        [code_dir],
        ["laravel_trans_helper", "laravel_lang_directive", "laravel_trans_function"],
        [".php", ".blade.php"],
        profile="laravel_php",
        locale_format="laravel_php",
        locale_keys={"lang.Add", "validation.required", "messages.saved"},
    )

    assert set(usage["static_occurrences"]) == {"lang.Add", "validation.required", "messages.saved"}
    assert usage["dynamic_usage_count"] == 3
    assert usage["dynamic_breakdown"]["laravel_native_dynamic"] == 3


def test_existing_framework_static_support_is_preserved(tmp_path: Path) -> None:
    code_dir = tmp_path / "src"
    code_dir.mkdir()
    (code_dir / "screen.dart").write_text("'home.title'.tr\ntr('ride.accepted');\n", encoding="utf-8")
    (code_dir / "page.tsx").write_text("t('common.save'); i18n.t('common.cancel');", encoding="utf-8")
    (code_dir / "component.vue").write_text("{{ $t('nav.home') }}", encoding="utf-8")

    usage = scan_code_usage(
        [code_dir],
        ["flutter_getx_tr", "flutter_tr_call", "react_t_function", "react_i18n_t", "vue_t_function"],
        [".dart", ".tsx", ".vue"],
    )

    assert "home.title" in usage["static_occurrences"]
    assert "ride.accepted" in usage["static_occurrences"]
    assert "common.save" in usage["static_occurrences"]
    assert "common.cancel" in usage["static_occurrences"]
    assert "nav.home" in usage["static_occurrences"]


def test_suspicious_translate_member_calls_do_not_create_confirmed_keys(tmp_path: Path) -> None:
    code_dir = tmp_path / "src"
    code_dir.mkdir()
    (code_dir / "widget.dart").write_text(
        "\n".join(
            [
                "Transform.translate(offset: offset, child: child);",
                "controller.translate('cta.title');",
                "'real.key'.tr;",
            ]
        ),
        encoding="utf-8",
    )

    usage = scan_code_usage(
        [code_dir],
        ["flutter_getx_tr", "flutter_translate", "flutter_dot_translate"],
        [".dart"],
    )

    assert usage["confirmed_static_usage"] == ["real.key"]
    assert usage["suspicious_usage_count"] == 2
    assert {item["candidate"] for item in usage["suspicious_usage"]} == {"cta.title", "offset: offset"}


def test_usage_scanner_infers_button_context(tmp_path: Path) -> None:
    code_dir = tmp_path / "src"
    code_dir.mkdir()
    (code_dir / "page.dart").write_text("TextButton(onPressed: save, child: 'common.save'.tr)\n", encoding="utf-8")

    usage = scan_code_usage([code_dir], ["flutter_getx_tr"], [".dart"])

    assert usage["usage_contexts"]["common.save"] == ["button"]
