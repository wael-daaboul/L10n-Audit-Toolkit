import json
from pathlib import Path
from types import SimpleNamespace

from fixes.apply_safe_fixes import apply_safe_changes, build_fix_plan, main


def test_safe_fixes_apply_only_safe_changes() -> None:
    issues = [
        {
            "source": "locale_qc",
            "key": "trimmed",
            "issue_type": "whitespace",
            "severity": "low",
            "message": "Trim",
            "details": {"old": " hello ", "new": "hello"},
        },
        {
            "source": "icu_message_audit",
            "key": "icu",
            "issue_type": "icu_branch_mismatch",
            "severity": "medium",
            "message": "Mismatch",
            "details": {"old": "{count, plural, other{{count} trips}}", "new": "{count, plural, other{رحلات}}"},
            "locale": "en/ar",
        },
    ]
    plan = build_fix_plan(issues)
    updated, applied = apply_safe_changes({"trimmed": " hello ", "icu": "{count, plural, other{{count} trips}}"}, plan, "en")
    assert updated["trimmed"] == "hello"
    assert updated["icu"] == "{count, plural, other{{count} trips}}"
    assert any(item["key"] == "trimmed" for item in applied)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_runtime(tmp_path: Path, *, locale_format: str, en_file: Path, ar_file: Path, results_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        locale_format=locale_format,
        en_file=en_file,
        ar_file=ar_file,
        source_locale="en",
        target_locales=("ar",),
        results_dir=results_dir,
    )


def test_safe_fixes_main_supports_json_locales(monkeypatch, tmp_path: Path) -> None:
    en_file = tmp_path / "assets" / "language" / "en.json"
    ar_file = tmp_path / "assets" / "language" / "ar.json"
    _write_json(en_file, {"trimmed": " hello ", "plain": "World"})
    _write_json(ar_file, {"trimmed": " مرحبا ", "plain": "العالم"})

    runtime = _make_runtime(tmp_path, locale_format="json", en_file=en_file, ar_file=ar_file, results_dir=tmp_path / "Results")
    monkeypatch.setattr("fixes.apply_safe_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("fixes.apply_safe_fixes.load_all_report_issues", lambda _results_dir: ({}, [], []))
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_safe_fixes.py",
            "--out-plan-json",
            str(runtime.results_dir / "fixes" / "fix_plan.json"),
            "--out-plan-xlsx",
            str(runtime.results_dir / "fixes" / "fix_plan.xlsx"),
            "--out-en-fixed",
            str(runtime.results_dir / "fixes" / "en.fixed.json"),
            "--out-ar-fixed",
            str(runtime.results_dir / "fixes" / "ar.fixed.json"),
            "--out-exports-dir",
            str(runtime.results_dir / "exports"),
        ],
    )

    main()

    fixed_en = json.loads((runtime.results_dir / "fixes" / "en.fixed.json").read_text(encoding="utf-8"))
    fixed_ar = json.loads((runtime.results_dir / "fixes" / "ar.fixed.json").read_text(encoding="utf-8"))
    assert fixed_en["trimmed"] == "hello"
    assert fixed_ar["trimmed"] == "مرحبا"
    assert (runtime.results_dir / "exports" / "en.json").exists()
    assert (runtime.results_dir / "exports" / "ar.json").exists()


def test_safe_fixes_main_supports_laravel_php_locales(monkeypatch, tmp_path: Path, fixtures_dir: Path) -> None:
    source_fixture = fixtures_dir / "laravel_php" / "commented"
    en_dir = tmp_path / "resources" / "lang" / "en"
    ar_dir = tmp_path / "resources" / "lang" / "ar"
    en_dir.mkdir(parents=True, exist_ok=True)
    ar_dir.mkdir(parents=True, exist_ok=True)
    (en_dir / "lang.php").write_text((source_fixture / "en" / "lang.php").read_text(encoding="utf-8"), encoding="utf-8")
    (ar_dir / "lang.php").write_text((source_fixture / "ar" / "lang.php").read_text(encoding="utf-8"), encoding="utf-8")

    runtime = _make_runtime(tmp_path, locale_format="laravel_php", en_file=en_dir, ar_file=ar_dir, results_dir=tmp_path / "Results")
    monkeypatch.setattr("fixes.apply_safe_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("fixes.apply_safe_fixes.load_all_report_issues", lambda _results_dir: ({}, [], []))
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_safe_fixes.py",
            "--out-plan-json",
            str(runtime.results_dir / "fixes" / "fix_plan.json"),
            "--out-plan-xlsx",
            str(runtime.results_dir / "fixes" / "fix_plan.xlsx"),
            "--out-en-fixed",
            str(runtime.results_dir / "fixes" / "en.fixed.json"),
            "--out-ar-fixed",
            str(runtime.results_dir / "fixes" / "ar.fixed.json"),
            "--out-exports-dir",
            str(runtime.results_dir / "exports"),
        ],
    )

    main()

    fixed_en = json.loads((runtime.results_dir / "fixes" / "en.fixed.json").read_text(encoding="utf-8"))
    fixed_ar = json.loads((runtime.results_dir / "fixes" / "ar.fixed.json").read_text(encoding="utf-8"))
    assert "lang.intro_link" in fixed_en
    assert "lang.intro_link" in fixed_ar
    assert (runtime.results_dir / "exports" / "en" / "lang.php").exists()
    assert (runtime.results_dir / "exports" / "ar" / "lang.php").exists()
