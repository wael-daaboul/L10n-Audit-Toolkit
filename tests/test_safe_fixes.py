import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.audit_runtime import AuditRuntimeError, compute_text_hash, read_simple_xlsx, write_simple_xlsx
from fixes.apply_review_fixes import main as review_main
from fixes.apply_safe_fixes import add_direct_locale_safety_pass, apply_safe_changes, build_fix_plan, main


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


def test_direct_safety_pass_preserves_newlines_tabs_and_placeholders() -> None:
    rows = add_direct_locale_safety_pass(
        {
            "error": "Error:\n%s",
            "double_break": "Hello\n\nWorld",
            "tabbed": "Hello\t%s",
            "arabic_lines": "مرحبا\n%s",
            "safe_spaces": "Hello  world",
        },
        "en",
    )
    keys = {(row["key"], row["issue_type"]) for row in rows}
    assert ("safe_spaces", "spacing") in keys
    assert ("error", "spacing") not in keys
    assert ("double_break", "spacing") not in keys
    assert ("tabbed", "spacing") not in keys
    assert ("arabic_lines", "spacing") not in keys


def test_build_fix_plan_preserves_provenance_for_same_replacement() -> None:
    plan = build_fix_plan(
        [
            {"source": "locale_qc", "key": "trimmed", "issue_type": "whitespace", "severity": "low", "message": "Trim left", "details": {"old": " x ", "new": "x"}},
            {"source": "grammar", "key": "trimmed", "issue_type": "style", "severity": "low", "message": "Trim style", "details": {"old": " x ", "new": "x", "rule_id": "CUSTOM::TRIM"}},
        ]
    )
    assert len(plan) == 1
    assert len(plan[0]["provenance"]) == 2


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
            "--out-applied-report",
            str(runtime.results_dir / "fixes" / "safe_fixes_applied_report.json"),
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
    applied_report = json.loads((runtime.results_dir / "fixes" / "safe_fixes_applied_report.json").read_text(encoding="utf-8"))
    assert fixed_en["trimmed"] == "hello"
    assert fixed_ar["trimmed"] == "مرحبا"
    assert applied_report["summary"]["keys_auto_fixed"] == 2
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
            "--out-applied-report",
            str(runtime.results_dir / "fixes" / "safe_fixes_applied_report.json"),
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


def test_apply_review_fixes_uses_approved_rows(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    _write_json(ar_file, {"welcome": "اهلا", "keep": "كما هو"})
    runtime = SimpleNamespace(
        results_dir=tmp_path / "Results",
        ar_file=ar_file,
        locale_format="json",
        source_locale="en",
        target_locales=("ar",),
    )
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    source_old_value = "اهلا"
    approved_new = "مرحبا"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "old_value": source_old_value,
                "issue_type": "confirmed_missing_key",
                "suggested_fix": "Welcome",
                "approved_new": approved_new,
                "status": "approved",
                "notes": "",
                "source_old_value": source_old_value,
                "source_hash": compute_text_hash(source_old_value),
                "suggested_hash": compute_text_hash(approved_new),
                "plan_id": "plan-1",
                "generated_at": "2026-03-08T00:00:00+00:00",
            },
            {
                "key": "keep",
                "locale": "ar",
                "old_value": "كما هو",
                "issue_type": "soft_terminology_drift",
                "suggested_fix": "",
                "approved_new": "",
                "status": "pending",
                "notes": "",
                "source_old_value": "كما هو",
                "source_hash": compute_text_hash("كما هو"),
                "suggested_hash": compute_text_hash(""),
                "plan_id": "plan-2",
                "generated_at": "2026-03-08T00:00:00+00:00",
            },
        ],
        ["key", "locale", "old_value", "issue_type", "suggested_fix", "approved_new", "status", "notes", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"],
        review_queue,
        sheet_name="Review Queue",
    )

    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr(
        "sys.argv",
        [
            "apply_review_fixes.py",
            "--review-queue",
            str(review_queue),
            "--out-final-json",
            str(runtime.results_dir / "final_locale" / "ar.final.json"),
            "--out-report",
            str(runtime.results_dir / "final_locale" / "review_fixes_report.json"),
        ],
    )

    review_main()

    final_payload = json.loads((runtime.results_dir / "final_locale" / "ar.final.json").read_text(encoding="utf-8"))
    report_payload = json.loads((runtime.results_dir / "final_locale" / "review_fixes_report.json").read_text(encoding="utf-8"))
    assert final_payload["welcome"] == "مرحبا"
    assert final_payload["keep"] == "كما هو"
    assert report_payload["summary"]["approved_rows_applied"] == 1
    assert report_payload["summary"]["approved_rows_skipped"] == 0


def test_apply_review_fixes_preserves_multiline_and_surrounding_whitespace(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    source_old = "قديم"
    approved_new = "  Error:\n%s  "
    _write_json(ar_file, {"welcome": source_old})
    runtime = SimpleNamespace(results_dir=tmp_path / "Results", ar_file=ar_file, locale_format="json", source_locale="en", target_locales=("ar",))
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "old_value": source_old,
                "issue_type": "confirmed_missing_key",
                "suggested_fix": approved_new,
                "approved_new": approved_new,
                "status": "approved",
                "notes": "",
                "source_old_value": source_old,
                "source_hash": compute_text_hash(source_old),
                "suggested_hash": compute_text_hash(approved_new),
                "plan_id": "plan-3",
                "generated_at": "2026-03-08T00:00:00+00:00",
            }
        ],
        ["key", "locale", "old_value", "issue_type", "suggested_fix", "approved_new", "status", "notes", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"],
        review_queue,
        sheet_name="Review Queue",
    )
    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("sys.argv", ["apply_review_fixes.py", "--review-queue", str(review_queue), "--out-final-json", str(runtime.results_dir / "final_locale" / "ar.final.json"), "--out-report", str(runtime.results_dir / "final_locale" / "review_fixes_report.json")])
    review_main()
    final_payload = json.loads((runtime.results_dir / "final_locale" / "ar.final.json").read_text(encoding="utf-8"))
    assert final_payload["welcome"] == approved_new


def test_apply_review_fixes_skips_stale_row(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    _write_json(ar_file, {"welcome": "تم التغيير"})
    runtime = SimpleNamespace(results_dir=tmp_path / "Results", ar_file=ar_file, locale_format="json", source_locale="en", target_locales=("ar",))
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "old_value": "اهلا",
                "issue_type": "confirmed_missing_key",
                "suggested_fix": "مرحبا",
                "approved_new": "مرحبا",
                "status": "approved",
                "notes": "",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-4",
                "generated_at": "2026-03-08T00:00:00+00:00",
            }
        ],
        ["key", "locale", "old_value", "issue_type", "suggested_fix", "approved_new", "status", "notes", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"],
        review_queue,
        sheet_name="Review Queue",
    )
    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("sys.argv", ["apply_review_fixes.py", "--review-queue", str(review_queue), "--out-final-json", str(runtime.results_dir / "final_locale" / "ar.final.json"), "--out-report", str(runtime.results_dir / "final_locale" / "review_fixes_report.json")])
    review_main()
    report_payload = json.loads((runtime.results_dir / "final_locale" / "review_fixes_report.json").read_text(encoding="utf-8"))
    assert report_payload["summary"]["approved_rows_applied"] == 0
    assert report_payload["skipped"][0]["reason"] == "stale_source"


def test_apply_review_fixes_rejects_duplicate_and_conflicting_rows(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    _write_json(ar_file, {"welcome": "اهلا"})
    runtime = SimpleNamespace(results_dir=tmp_path / "Results", ar_file=ar_file, locale_format="json", source_locale="en", target_locales=("ar",))
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    base_fields = {
        "key": "welcome",
        "locale": "ar",
        "old_value": "اهلا",
        "issue_type": "confirmed_missing_key",
        "status": "approved",
        "notes": "",
        "source_old_value": "اهلا",
        "source_hash": compute_text_hash("اهلا"),
        "generated_at": "2026-03-08T00:00:00+00:00",
    }
    write_simple_xlsx(
        [
            {**base_fields, "suggested_fix": "مرحبا", "approved_new": "مرحبا", "suggested_hash": compute_text_hash("مرحبا"), "plan_id": "plan-a"},
            {**base_fields, "suggested_fix": "أهلًا", "approved_new": "أهلًا", "suggested_hash": compute_text_hash("أهلًا"), "plan_id": "plan-b"},
        ],
        ["key", "locale", "old_value", "issue_type", "suggested_fix", "approved_new", "status", "notes", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"],
        review_queue,
        sheet_name="Review Queue",
    )
    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("sys.argv", ["apply_review_fixes.py", "--review-queue", str(review_queue), "--out-final-json", str(runtime.results_dir / "final_locale" / "ar.final.json"), "--out-report", str(runtime.results_dir / "final_locale" / "review_fixes_report.json")])
    review_main()
    report_payload = json.loads((runtime.results_dir / "final_locale" / "review_fixes_report.json").read_text(encoding="utf-8"))
    reasons = {item["reason"] for item in report_payload["skipped"]}
    assert "conflicting_approved_rows" in reasons


def test_apply_review_fixes_rejects_malformed_row(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    _write_json(ar_file, {"welcome": "اهلا"})
    runtime = SimpleNamespace(results_dir=tmp_path / "Results", ar_file=ar_file, locale_format="json", source_locale="en", target_locales=("ar",))
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    write_simple_xlsx(
        [{"key": "welcome", "locale": "ar", "issue_type": "confirmed_missing_key", "approved_new": "مرحبا", "status": "approved"}],
        ["key", "locale", "issue_type", "approved_new", "status"],
        review_queue,
        sheet_name="Review Queue",
    )
    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("sys.argv", ["apply_review_fixes.py", "--review-queue", str(review_queue), "--out-final-json", str(runtime.results_dir / "final_locale" / "ar.final.json"), "--out-report", str(runtime.results_dir / "final_locale" / "review_fixes_report.json")])
    with pytest.raises(AuditRuntimeError):
        review_main()


def test_apply_review_fixes_skips_manual_hash_edit(monkeypatch, tmp_path: Path) -> None:
    ar_file = tmp_path / "ar.json"
    _write_json(ar_file, {"welcome": "اهلا"})
    runtime = SimpleNamespace(results_dir=tmp_path / "Results", ar_file=ar_file, locale_format="json", source_locale="en", target_locales=("ar",))
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "old_value": "اهلا",
                "issue_type": "confirmed_missing_key",
                "suggested_fix": "مرحبا",
                "approved_new": "تم تحريرها يدويًا",
                "status": "approved",
                "notes": "",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-5",
                "generated_at": "2026-03-08T00:00:00+00:00",
            }
        ],
        ["key", "locale", "old_value", "issue_type", "suggested_fix", "approved_new", "status", "notes", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"],
        review_queue,
        sheet_name="Review Queue",
    )
    monkeypatch.setattr("fixes.apply_review_fixes.load_runtime", lambda _script_path: runtime)
    monkeypatch.setattr("sys.argv", ["apply_review_fixes.py", "--review-queue", str(review_queue), "--out-final-json", str(runtime.results_dir / "final_locale" / "ar.final.json"), "--out-report", str(runtime.results_dir / "final_locale" / "review_fixes_report.json")])
    review_main()
    report_payload = json.loads((runtime.results_dir / "final_locale" / "review_fixes_report.json").read_text(encoding="utf-8"))
    assert report_payload["skipped"][0]["reason"] == "suggested_hash_mismatch"
