from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from l10n_audit.core.audit_runtime import AuditRuntimeError, compute_text_hash
from l10n_audit.core.audit_report_utils import load_all_report_issues
from l10n_audit.core.audit_runtime import read_simple_xlsx
from l10n_audit.reports.report_aggregator import (
    REVIEW_PROJECTION_COLUMNS,
    REVIEW_QUEUE_WORKBOOK_COLUMNS,
    UNRESOLVED_LOOKUP_SOURCE_HASH,
    build_human_review_queue,
    build_review_queue,
    _resolve_issue_locale,
    suggested_fix_for_issue,
)

from conftest import write_json


def test_report_loader_merges_and_dedupes(tmp_path: Path) -> None:
    results = tmp_path / "Results"
    write_json(
        results / "per_tool" / "localization" / "localization_audit_pro.json",
        {"findings": [{"key": "x", "issue_type": "missing_in_ar", "message": "Missing", "locale": "ar"}]},
    )
    write_json(
        results / "per_tool" / "en_locale_qc" / "en_locale_qc_report.json",
        {
            "findings": [
                {"key": "trimmed", "issue_type": "whitespace", "severity": "low", "message": "Trim", "old": " x ", "new": "x"},
                {"key": "trimmed", "issue_type": "whitespace", "severity": "low", "message": "Trim", "old": " x ", "new": "x"},
            ]
        },
    )

    _reports, issues, missing = load_all_report_issues(results)
    assert len(issues) == 2
    assert missing


def test_report_aggregator_builds_review_queue_and_hides_auto_safe(tmp_path: Path) -> None:
    results = tmp_path / "Results"
    write_json(
        results / "per_tool" / "localization" / "localization_audit_pro.json",
        {"findings": [{"key": "welcome", "issue_type": "confirmed_missing_key", "message": "Missing", "locale": "ar"}]},
    )
    issues = load_all_report_issues(results)[1]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"welcome": "Welcome"})
    write_json(runtime.ar_file, {})

    rows = build_review_queue(issues, runtime)
    assert len(rows) == 1
    row = rows[0]
    assert row["key"] == "welcome"
    assert row["locale"] == "ar"
    assert row["old_value"] == ""
    assert row["issue_type"] == "confirmed_missing_key"
    assert row["suggested_fix"] == "Welcome"
    assert row["approved_new"] == ""
    assert row["status"] == "pending"
    assert "Missing" in row["notes"]
    assert row["source_old_value"] == ""
    assert row["source_hash"]
    assert row["suggested_hash"]
    assert row["plan_id"]
    assert row["generated_at"]


def test_report_aggregator_uses_semantic_candidate_value_for_review_rows(tmp_path: Path) -> None:
    results = tmp_path / "Results"
    write_json(
        results / "per_tool" / "ar_semantic_qc" / "ar_semantic_qc_report.json",
        {
            "findings": [
                {
                    "key": "profile.helper",
                    "issue_type": "possible_meaning_loss",
                    "severity": "medium",
                    "message": "Meaning loss",
                    "old": "الملف الشخصي للمتابعة",
                    "candidate_value": "احفظ الملف الشخصي للمتابعة.",
                }
            ]
        },
    )
    issues = load_all_report_issues(results)[1]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"profile.helper": "Save your profile to continue."})
    write_json(runtime.ar_file, {"profile.helper": "الملف الشخصي للمتابعة"})

    rows = build_review_queue(issues, runtime)
    assert len(rows) == 1
    assert rows[0]["locale"] == "ar"
    assert rows[0]["suggested_fix"] == "احفظ الملف الشخصي للمتابعة."


def test_simple_xlsx_reader_round_trips(tmp_path: Path) -> None:
    from l10n_audit.core.audit_runtime import write_simple_xlsx

    path = tmp_path / "queue.xlsx"
    rows = [{"key": "a", "status": "pending"}, {"key": "b", "status": "approved"}]
    write_simple_xlsx(rows, ["key", "status"], path, sheet_name="Queue")

    assert read_simple_xlsx(path) == rows


def test_simple_xlsx_reader_supports_reordered_columns_and_multiline_unicode(tmp_path: Path) -> None:
    from l10n_audit.core.audit_runtime import write_simple_xlsx

    path = tmp_path / "queue_reordered.xlsx"
    rows = [{"candidate_value": "مرحبا\n%s", "status": "approved", "key": "welcome"}]
    write_simple_xlsx(rows, ["candidate_value", "status", "key"], path, sheet_name="Queue")
    assert read_simple_xlsx(path, required_columns=["key", "status", "candidate_value"]) == rows


def test_simple_xlsx_reader_uses_cell_references_not_encounter_order(tmp_path: Path) -> None:
    from l10n_audit.core.audit_runtime import write_simple_xlsx

    path = tmp_path / "queue_cells.xlsx"
    rows = [{"key": "welcome", "status": "approved"}]
    write_simple_xlsx(rows, ["key", "status"], path, sheet_name="Queue")
    with ZipFile(path, "r") as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    worksheet = contents["xl/worksheets/sheet1.xml"].decode("utf-8")
    worksheet = worksheet.replace('<c r="A2" t="s"><v>2</v></c><c r="B2" t="s"><v>3</v></c>', '<c r="B2" t="s"><v>3</v></c><c r="A2" t="s"><v>2</v></c>')
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, worksheet.encode("utf-8") if name == "xl/worksheets/sheet1.xml" else content)
    assert read_simple_xlsx(path) == rows


def test_simple_xlsx_reader_rejects_missing_required_columns(tmp_path: Path) -> None:
    from l10n_audit.core.audit_runtime import write_simple_xlsx

    path = tmp_path / "queue_missing.xlsx"
    write_simple_xlsx([{"key": "welcome"}], ["key"], path, sheet_name="Queue")
    with pytest.raises(AuditRuntimeError):
        read_simple_xlsx(path, required_columns=["key", "status"])


def test_resolve_issue_locale_maps_grammar_to_en():
    issue = {
        "source": "grammar",
        "key": "welcome.title",
    }
    assert _resolve_issue_locale(issue) == "en"


def test_suggested_fix_for_issue_reads_details_new_when_top_level_missing():
    issue = {
        "source": "grammar",
        "key": "any_time",
        "details": {
            "old": "Any time",
            "new": "At any time.",
        },
    }
    assert suggested_fix_for_issue(issue, {}, {}) == "At any time."


def test_suggested_fix_for_issue_prefers_top_level_over_details():
    issue = {
        "source": "ai_review",
        "suggested_fix": "احفظ",
        "details": {
            "new": "حفظ."
        },
    }
    assert suggested_fix_for_issue(issue, {}, {}) == "احفظ"


def test_build_review_queue_projects_grammar_locale_and_suggestion(tmp_path: Path):
    issues = [
        {
            "source": "grammar",
            "key": "any_time",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "details": {
                "old": "Any time",
                "new": "At any time.",
            },
        }
    ]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"any_time": "Any time"})
    write_json(runtime.ar_file, {})

    rows = build_review_queue(issues, runtime)

    assert len(rows) == 1
    row = rows[0]

    assert row["key"] == "any_time"
    assert row["locale"] == "en"
    assert row["suggested_fix"] == "At any time."


def test_build_review_queue_collision_between_en_locale_qc_and_grammar_preserves_grammar_suggestion(tmp_path: Path):
    issues = [
        {
            "source": "en_locale_qc",
            "key": "any_time",
            "issue_type": "whitespace",
            "severity": "low",
            "message": "Whitespace issue",
            "details": {
                "old": "Any time ",
            },
        },
        {
            "source": "grammar",
            "key": "any_time",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "details": {
                "old": "Any time",
                "new": "At any time.",
            },
        },
    ]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"any_time": "Any time"})
    write_json(runtime.ar_file, {})

    rows = build_review_queue(issues, runtime)

    # Collision results in 1 row (key, locale)
    assert len(rows) == 1
    row = rows[0]

    assert row["key"] == "any_time"
    assert row["locale"] == "en"
    # grammar suggestion should be preserved
    assert row["suggested_fix"] == "At any time."


class TestAggregatorPatches:
    
    # ==========================================
    # 1. اختبارات أزمة الهوية (Identity Crisis)
    # ==========================================
    def test_resolve_issue_locale_maps_grammar_to_en(self):
        """التحقق من أن الجرامر يُنسب للغة الإنجليزية دائماً"""
        issue = {"source": "grammar", "key": "welcome_msg"}
        assert _resolve_issue_locale(issue) == "en"

    def test_resolve_issue_locale_maps_ai_review_to_ar(self):
        """التحقق من أن اقتراحات الذكاء الاصطناعي تُنسب للعربية"""
        issue = {"source": "ai_review", "key": "welcome_msg"}
        assert _resolve_issue_locale(issue) == "ar"

    # ==========================================
    # 2. اختبارات عقد البيانات (Data Contract)
    # ==========================================
    def test_suggested_fix_extracts_from_replacements_list(self):
        """التحقق من نجاح سحب الاقتراح إذا كان داخل مصفوفة (كما في LanguageTool)"""
        issue = {
            "source": "grammar",
            "details": {
                "replacements": ["talk to", "speak with"] # يجب أن يسحب العنصر الأول
            }
        }
        # نمرر قواميس فارغة لأننا نختبر استخراج الاقتراح فقط
        assert suggested_fix_for_issue(issue, {}, {}) == "talk to"

    def test_suggested_fix_extracts_from_replacements_string(self):
        """التحقق من نجاح السحب إذا كانت replacements نصاً مباشراً (للحماية من الاستثناءات)"""
        issue = {
            "source": "grammar",
            "details": {
                "replacements": "talk to us" 
            }
        }
        assert suggested_fix_for_issue(issue, {}, {}) == "talk to us"


def test_human_review_queue_workbook_contract_excludes_approved_new(tmp_path: Path) -> None:
    issues = [
        {
            "source": "grammar",
            "key": "any_time",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "details": {
                "old": "Any time",
                "new": "At any time.",
            },
        }
    ]

    runtime = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()
    write_json(runtime.en_file, {"any_time": "Any time"})
    write_json(runtime.ar_file, {})

    projection_rows = build_review_queue(issues, runtime)
    human_rows = build_human_review_queue(projection_rows)

    assert list(human_rows[0].keys()) == REVIEW_QUEUE_WORKBOOK_COLUMNS
    assert "approved_new" not in human_rows[0]
    assert human_rows[0]["current_value"] == "Any time"
    assert human_rows[0]["candidate_value"] == "At any time."
    assert human_rows[0]["review_note"] == projection_rows[0]["notes"]


def test_human_review_queue_is_not_projection_alias() -> None:
    projection_rows = [
        {
            "key": "welcome",
            "locale": "ar",
            "old_value": "اهلا",
            "issue_type": "grammar",
            "suggested_fix": "مرحبا",
            "approved_new": "",
            "needs_review": "Yes",
            "status": "pending",
            "notes": "Needs review",
            "context_type": "",
            "context_flags": "",
            "semantic_risk": "",
            "lt_signals": "",
            "review_reason": "",
            "source_old_value": "اهلا",
            "source_hash": "source-hash",
            "suggested_hash": "suggested-hash",
            "plan_id": "plan-1",
            "generated_at": "2026-03-08T00:00:00+00:00",
            "provenance": "grammar|grammar|medium",
        }
    ]

    human_rows = build_human_review_queue(projection_rows)

    assert list(projection_rows[0].keys()) == REVIEW_PROJECTION_COLUMNS
    assert list(human_rows[0].keys()) == REVIEW_QUEUE_WORKBOOK_COLUMNS
    assert human_rows[0]["candidate_value"] == projection_rows[0]["suggested_fix"]
    assert "approved_new" not in human_rows[0]


def test_run_stage_emits_review_queue_xlsx_not_review_projection_xlsx(monkeypatch, tmp_path: Path) -> None:
    from l10n_audit.reports.report_aggregator import run_stage

    runtime = SimpleNamespace(
        project_root=tmp_path,
        results_dir=tmp_path / "Results",
        en_file=tmp_path / "en.json",
        ar_file=tmp_path / "ar.json",
        source_locale="en",
        target_locales=("ar",),
    )
    runtime.results_dir.mkdir(parents=True, exist_ok=True)
    write_json(runtime.en_file, {"welcome": "Welcome"})
    write_json(runtime.ar_file, {"welcome": "اهلا"})

    issue = {
        "source": "grammar",
        "key": "welcome",
        "locale": "ar",
        "issue_type": "grammar",
        "severity": "medium",
        "message": "Grammar check",
        "current_value": "اهلا",
        "suggested_fix": "مرحبا",
    }

    monkeypatch.setattr(
        "l10n_audit.reports.report_aggregator.load_all_report_issues",
        lambda *args, **kwargs: ({"grammar": [issue]}, [issue], []),
    )
    monkeypatch.setattr(
        "l10n_audit.reports.report_aggregator.load_locale_mapping",
        lambda path, *_args, **_kwargs: {"welcome": "Welcome"} if path == runtime.en_file else {"welcome": "اهلا"},
    )
    monkeypatch.setattr(
        "l10n_audit.reports.report_aggregator.build_fix_plan",
        lambda issues: [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "grammar",
                "candidate_value": "مرحبا",
                "classification": "review_required",
            }
        ],
    )

    options = SimpleNamespace(
        input_report=None,
        strict_deprecations=False,
        effective_output_dir=lambda results_dir: results_dir,
    )

    artifacts = run_stage(runtime, options)
    artifact_names = [artifact.name for artifact in artifacts]

    assert "Review Queue (Excel)" in artifact_names
    assert "Review Projection (Excel)" not in artifact_names
    assert (runtime.results_dir / "review" / "review_queue.xlsx").exists()
    assert not (runtime.results_dir / "review" / "review_projection.xlsx").exists()

def test_build_review_queue_handles_empty_issue_types(tmp_path: Path) -> None:
    issues = [
        {"key": "k1", "issue_type": None, "message": "msg1", "source": "test", "details": {"new": "fix1"}},
        {"key": "k2", "issue_type": "", "message": "msg2", "source": "test", "details": {"new": "fix2"}},
        {"key": "k3", "issue_type": "   ", "message": "msg3", "source": "test", "details": {"new": "fix3"}},
    ]
    runtime = type("Runtime", (), {
        "en_file": tmp_path / "en.json",
        "ar_file": tmp_path / "ar.json",
        "locale_format": "json",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()
    write_json(runtime.en_file, {"k1": "v1", "k2": "v2", "k3": "v3"})
    write_json(runtime.ar_file, {})

    rows = build_review_queue(issues, runtime)
    assert len(rows) == 3
    for row in rows:
        assert row["issue_type"] == "unknown", f"Failed for {row['key']}: issue_type={row['issue_type']}"


def test_build_review_queue_laravel_resolves_canonical_key_via_locale_context(tmp_path: Path) -> None:
    en_dir = tmp_path / "lang" / "en"
    ar_dir = tmp_path / "lang" / "ar"
    en_dir.mkdir(parents=True)
    ar_dir.mkdir(parents=True)
    (en_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'These credentials do not match our records.']];",
        encoding="utf-8",
    )
    (ar_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'بيانات الاعتماد لا تطابق سجلاتنا.']];",
        encoding="utf-8",
    )
    runtime = type("Runtime", (), {
        "en_file": en_dir,
        "ar_file": ar_dir,
        "locale_format": "laravel_php",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()
    issues = [
        {
            "key": "messages.auth.failed",
            "issue_type": "empty_en",
            "severity": "medium",
            "message": "Populate English text",
            "source": "localization",
            "suggestion": "Use a better source string",
        }
    ]

    rows = build_review_queue(issues, runtime)

    assert len(rows) == 1
    assert rows[0]["locale"] == "en"
    assert rows[0]["old_value"] == "These credentials do not match our records."
    assert rows[0]["source_hash"] == compute_text_hash("These credentials do not match our records.")


def test_build_review_queue_laravel_resolves_unambiguous_suffix_key(tmp_path: Path) -> None:
    en_dir = tmp_path / "lang" / "en"
    ar_dir = tmp_path / "lang" / "ar"
    en_dir.mkdir(parents=True)
    ar_dir.mkdir(parents=True)
    (en_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'These credentials do not match our records.']];",
        encoding="utf-8",
    )
    (ar_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'بيانات الاعتماد لا تطابق سجلاتنا.']];",
        encoding="utf-8",
    )
    runtime = type("Runtime", (), {
        "en_file": en_dir,
        "ar_file": ar_dir,
        "locale_format": "laravel_php",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()
    issues = [
        {
            "key": "auth.failed",
            "locale": "en",
            "issue_type": "style",
            "severity": "medium",
            "message": "Populate source text",
            "source": "en_locale_qc",
            "suggestion": "Use a better source string",
        }
    ]

    rows = build_review_queue(issues, runtime)

    assert len(rows) == 1
    assert rows[0]["old_value"] == "These credentials do not match our records."


def test_build_review_queue_failed_lookup_uses_unresolved_hash_sentinel(tmp_path: Path) -> None:
    en_dir = tmp_path / "lang" / "en"
    ar_dir = tmp_path / "lang" / "ar"
    en_dir.mkdir(parents=True)
    ar_dir.mkdir(parents=True)
    (en_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'These credentials do not match our records.']];",
        encoding="utf-8",
    )
    (ar_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'بيانات الاعتماد لا تطابق سجلاتنا.']];",
        encoding="utf-8",
    )
    runtime = type("Runtime", (), {
        "en_file": en_dir,
        "ar_file": ar_dir,
        "locale_format": "laravel_php",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()
    issues = [
        {
            "key": "lang.auth.failed",
            "locale": "en",
            "issue_type": "style",
            "severity": "medium",
            "message": "Lookup should fail deterministically",
            "source": "en_locale_qc",
            "suggestion": "Use a better source string",
        }
    ]

    rows = build_review_queue(issues, runtime)

    assert len(rows) == 1
    assert rows[0]["old_value"] == ""
    assert rows[0]["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH
    assert rows[0]["source_hash"] != compute_text_hash("")


def test_build_review_queue_true_empty_translation_keeps_empty_hash(tmp_path: Path) -> None:
    en_dir = tmp_path / "lang" / "en"
    ar_dir = tmp_path / "lang" / "ar"
    en_dir.mkdir(parents=True)
    ar_dir.mkdir(parents=True)
    (en_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => '']];",
        encoding="utf-8",
    )
    (ar_dir / "messages.php").write_text(
        "<?php return ['auth' => ['failed' => 'بيانات الاعتماد لا تطابق سجلاتنا.']];",
        encoding="utf-8",
    )
    runtime = type("Runtime", (), {
        "en_file": en_dir,
        "ar_file": ar_dir,
        "locale_format": "laravel_php",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()
    issues = [
        {
            "key": "messages.auth.failed",
            "locale": "en",
            "issue_type": "style",
            "severity": "medium",
            "message": "True empty source string",
            "source": "en_locale_qc",
            "suggestion": "Use a better source string",
        }
    ]

    rows = build_review_queue(issues, runtime)

    assert len(rows) == 1
    assert rows[0]["old_value"] == ""
    assert rows[0]["source_hash"] == compute_text_hash("")

def test_hydrate_review_queue_rejects_empty_issue_types() -> None:
    from l10n_audit.reports.report_aggregator import _normalize_review_row
    dirty_row = {"key": "x", "issue_type": "   ", "locale": "ar"}
    clean_row = _normalize_review_row(dirty_row)
    assert clean_row["issue_type"] == "unknown"

    dirty_row2 = {"key": "x", "issue_type": None, "locale": "ar"}
    clean_row2 = _normalize_review_row(dirty_row2)
    assert clean_row2["issue_type"] == "unknown"

    dirty_row3 = {"key": "x", "issue_type": "", "locale": "ar"}
    clean_row3 = _normalize_review_row(dirty_row3)
    assert clean_row3["issue_type"] == "unknown"

def test_load_hydrated_report_normalizes_empty_issue_types(tmp_path: Path) -> None:
    from l10n_audit.core.audit_report_utils import load_hydrated_report
    report_path = tmp_path / "final_audit_report.json"
    write_json(
        report_path,
        {
            "issues": [
                {"key": "a", "issue_type": ""},
                {"key": "b", "issue_type": "   "},
                {"key": "c", "issue_type": None},
                {"key": "d", "issue_type": "valid_type"},
            ]
        }
    )
    
    payload, issues, missing = load_hydrated_report(report_path)
    assert len(issues) == 4
    for issue in issues:
        if issue["key"] == "d":
            assert issue["issue_type"] == "valid_type"
        else:
            assert issue["issue_type"] == "unknown", f"Failed for key {issue['key']} with {issue['issue_type']}"

def test_load_from_master_normalizes_empty_issue_types(tmp_path: Path) -> None:
    from l10n_audit.reports.report_aggregator import load_from_master
    master_path = tmp_path / "audit_master.json"
    write_json(
        master_path,
        {
            "issue_inventory": [
                {"key": "i1", "issue_type": ""},
            ],
            "review_projection": {
                "json_rows": [
                    {"key": "r1", "issue_type": "   "},
                ]
            }
        }
    )
    
    stub, issues, review_rows, missing = load_from_master(master_path)
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "unknown"
    assert len(review_rows) == 1
    assert review_rows[0]["issue_type"] == "unknown"
