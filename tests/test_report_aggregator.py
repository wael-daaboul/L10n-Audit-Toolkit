from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from l10n_audit.core.audit_runtime import AuditRuntimeError
from l10n_audit.core.audit_report_utils import load_all_report_issues
from l10n_audit.core.audit_runtime import read_simple_xlsx
from l10n_audit.reports.report_aggregator import build_review_queue, _resolve_issue_locale, suggested_fix_for_issue

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
    rows = [{"approved_new": "مرحبا\n%s", "status": "approved", "key": "welcome"}]
    write_simple_xlsx(rows, ["approved_new", "status", "key"], path, sheet_name="Queue")
    assert read_simple_xlsx(path, required_columns=["key", "status", "approved_new"]) == rows


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
