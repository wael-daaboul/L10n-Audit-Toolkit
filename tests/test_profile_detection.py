from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.audit_runtime import AuditRuntimeError, load_runtime


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_temp_toolkit(tmp_path: Path, config_payload: dict[str, object]) -> Path:
    project_root = tmp_path / "project"
    tools_dir = project_root / "tools"
    config_dir = tools_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profiles_src = Path(__file__).resolve().parents[1] / "config" / "project_profiles.json"
    (config_dir / "project_profiles.json").write_text(profiles_src.read_text(encoding="utf-8"), encoding="utf-8")
    (config_dir / "config.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return tools_dir


def test_manual_profile_override_remains_authoritative(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "flutter_getx_json",
            "project_root": "..",
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "artisan", "")
    _write(project_root / "resources/lang/en/messages.php", "<?php return ['login' => 'Login'];")
    _write(project_root / "resources/lang/ar/messages.php", "<?php return ['login' => 'تسجيل الدخول'];")
    _write(project_root / "app/Http/Controller.php", "<?php")

    runtime = load_runtime(tools_dir, validate=False)
    assert runtime.project_profile == "flutter_getx_json"
    assert runtime.profile_selection_mode == "manual"
    assert runtime.profile_reasons == ("manual config override: flutter_getx_json",)


def test_autodetect_selects_laravel_php_with_reasons(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "auto",
            "project_root": "..",
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "artisan", "")
    _write(project_root / "resources/lang/en/messages.php", "<?php return ['login' => 'Login'];")
    _write(project_root / "resources/lang/ar/messages.php", "<?php return ['login' => 'تسجيل الدخول'];")
    _write(project_root / "resources/views/home.blade.php", "{{ __('messages.login') }}")
    _write(project_root / "routes/web.php", "<?php")
    _write(project_root / "app/Http/Controller.php", "<?php")

    runtime = load_runtime(tools_dir, validate=False)
    assert runtime.project_profile == "laravel_php"
    assert runtime.profile_selection_mode == "auto"
    assert runtime.profile_score >= 35
    assert any("artisan" in reason for reason in runtime.profile_reasons)
    assert any("resources/lang/en" in reason for reason in runtime.profile_reasons)


def test_autodetected_laravel_php_validates_runtime_paths(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "auto",
            "project_root": "..",
            "locale_format": "json",
            "locales_dir": "assets/language",
            "en_file": "assets/language/en.json",
            "ar_file": "assets/language/ar.json",
            "code_dir": "lib",
            "code_dirs": ["lib"],
            "locale_paths": {
                "en": "assets/language/en.json",
                "ar": "assets/language/ar.json",
            },
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "artisan", "")
    _write(project_root / "resources/lang/en/messages.php", "<?php return ['login' => 'Login'];")
    _write(project_root / "resources/lang/ar/messages.php", "<?php return ['login' => 'تسجيل الدخول'];")
    _write(project_root / "resources/views/home.blade.php", "{{ __('messages.login') }}")
    _write(project_root / "routes/web.php", "<?php")
    _write(project_root / "app/Http/Controller.php", "<?php")

    runtime = load_runtime(tools_dir, validate=True)
    assert runtime.project_profile == "laravel_php"
    assert runtime.locale_format == "laravel_php"
    assert runtime.en_file == (project_root / "resources/lang/en").resolve()
    assert runtime.ar_file == (project_root / "resources/lang/ar").resolve()
    assert runtime.code_dir == (project_root / "app").resolve()


def test_missing_project_profile_uses_auto_detection(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_root": "..",
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;")

    runtime = load_runtime(tools_dir, validate=False)
    assert runtime.project_profile == "flutter_getx_json"
    assert runtime.profile_selection_mode == "auto"


def test_autodetect_handles_default_project_root_dot_when_toolkit_is_nested(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "auto",
            "project_root": ".",
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;")

    runtime = load_runtime(tools_dir, validate=False)
    assert runtime.project_profile == "flutter_getx_json"
    assert runtime.project_root == project_root.resolve()


def test_autodetect_fails_when_ambiguous(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "auto",
            "project_root": "..",
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "package.json", '{"name":"web-app"}')
    _write(project_root / "src/app.ts", "export const x = 1;")
    _write(project_root / "src/pages/index.ts", "export default 1;")

    with pytest.raises(AuditRuntimeError, match="ambiguous|confidence"):
        load_runtime(tools_dir, validate=True)


def test_manual_flutter_profile_validates_legacy_json_paths(tmp_path: Path) -> None:
    tools_dir = _make_temp_toolkit(
        tmp_path,
        {
            "project_profile": "flutter_getx_json",
            "project_root": "..",
            "locales_dir": "assets/language",
            "en_file": "assets/language/en.json",
            "ar_file": "assets/language/ar.json",
            "code_dir": "lib",
            "code_dirs": ["lib"],
        },
    )
    project_root = tools_dir.parent
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;")

    runtime = load_runtime(tools_dir, validate=True)
    assert runtime.project_profile == "flutter_getx_json"
    assert runtime.en_file == (project_root / "assets/language/en.json").resolve()
    assert runtime.code_dir == (project_root / "lib").resolve()
