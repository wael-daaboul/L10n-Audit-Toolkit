"""
tests/test_h2_promotion_report.py

H2 Machine-Readable Promotion Report tests for the Review/Apply Contract Hardening track.

Verifies:
  1. prepare-apply emits a report with a top-level 'rows' key
  2. promoted rows appear with outcome=PROMOTION_OUTCOME_PROMOTED and
     reason_code='all_checks_passed'
  3. rejected rows appear with outcome=PROMOTION_OUTCOME_REJECTED and
     the correct rejection reason_code
  4. 'rows' length equals total input rows (every row accounted for)
  5. row order in 'rows' matches input order
  6. 'rejections' backward-compat key still present and unchanged
  7. 'summary' key still present and correct
  8. promotion decisions are unchanged by the report additions
  9. per-row identity fields (key, locale, plan_id) are preserved in 'rows'
 10. empty workbook produces empty 'rows' list (not absent key)
 11. PROMOTION_OUTCOME_PROMOTED / REJECTED constants are stable strings
 12. H3 plan-id rejections appear in 'rows' with stale_plan_id reason_code
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.fixes.fix_merger import (
    PROMOTION_OUTCOME_PROMOTED,
    PROMOTION_OUTCOME_REJECTED,
    REVIEW_FINAL_COLUMNS,
    STALE_PLAN_ID_REASON_CODE,
    prepare_apply_workbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QUEUE_COLUMNS = [
    "key", "locale", "issue_type", "current_value", "candidate_value",
    "status", "review_note", "source_old_value", "source_hash",
    "suggested_hash", "plan_id", "generated_at",
]


def _queue_row(**overrides) -> dict:
    row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "current_value": "فشل تسجيل الدخول",
        "candidate_value": "فشل.",
        "status": "approved",
        "review_note": "",
        "source_old_value": "فشل تسجيل الدخول",
        "source_hash": compute_text_hash("فشل تسجيل الدخول"),
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-h2-test",
        "generated_at": "2026-04-13T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict]) -> None:
    write_simple_xlsx(rows, _QUEUE_COLUMNS, path, sheet_name="Review Queue")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------

class TestPromotionOutcomeConstants:
    def test_promoted_constant_is_stable_string(self) -> None:
        assert PROMOTION_OUTCOME_PROMOTED == "promoted"

    def test_rejected_constant_is_stable_string(self) -> None:
        assert PROMOTION_OUTCOME_REJECTED == "rejected"

    def test_constants_are_distinct(self) -> None:
        assert PROMOTION_OUTCOME_PROMOTED != PROMOTION_OUTCOME_REJECTED


# ---------------------------------------------------------------------------
# 2. Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_has_rows_key(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "report.json"
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(queue, final, report_path)

        assert "rows" in payload

    def test_report_has_summary_key(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert "summary" in payload

    def test_report_has_rejections_key_for_backward_compat(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert "rejections" in payload

    def test_rows_is_persisted_in_json_file(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()])
        prepare_apply_workbook(queue, final, report_path)
        on_disk = _read_json(report_path)
        assert "rows" in on_disk

    def test_empty_workbook_produces_empty_rows_list_not_absent_key(
        self, tmp_path: Path
    ) -> None:
        """Zero input rows → 'rows' key must exist and be []."""
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert "rows" in payload
        assert payload["rows"] == []


# ---------------------------------------------------------------------------
# 3. Promoted rows
# ---------------------------------------------------------------------------

class TestPromotedRowsInReport:
    def test_promoted_row_appears_in_rows_list(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(key="auth.failed")])
        payload = prepare_apply_workbook(queue, final, report_path)

        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["outcome"] == PROMOTION_OUTCOME_PROMOTED

    def test_promoted_row_has_all_checks_passed_reason_code(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert payload["rows"][0]["reason_code"] == "all_checks_passed"

    def test_promoted_row_carries_identity_fields(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(key="nav.home", locale="ar", plan_id="plan-x")])
        payload = prepare_apply_workbook(queue, final, report_path)
        row_record = payload["rows"][0]
        assert row_record["key"] == "nav.home"
        assert row_record["locale"] == "ar"
        assert row_record["plan_id"] == "plan-x"

    def test_promoted_row_has_row_index(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert "row_index" in payload["rows"][0]
        assert payload["rows"][0]["row_index"] == 2  # first data row = row 2


# ---------------------------------------------------------------------------
# 4. Rejected rows
# ---------------------------------------------------------------------------

class TestRejectedRowsInReport:
    def test_rejected_row_appears_in_rows_list(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(status="pending")])
        payload = prepare_apply_workbook(queue, final, report_path)

        assert len(payload["rows"]) == 1
        assert payload["rows"][0]["outcome"] == PROMOTION_OUTCOME_REJECTED

    def test_rejected_row_carries_correct_reason_code(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(status="pending")])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert payload["rows"][0]["reason_code"] == "invalid_status_for_freeze"

    def test_hash_mismatch_rejection_appears_with_correct_reason(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Use disable flag: in canonical mode source_hash alone is not
        # sufficient to cause mismatch when source_old_value == current_value.
        monkeypatch.setenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD_DISABLE", "1")
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(source_hash=compute_text_hash("DIFFERENT_VALUE"))
        ])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert payload["rows"][0]["reason_code"] == "source_hash_mismatch"

    def test_missing_required_field_rejection_appears_with_correct_reason(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(key="")])
        payload = prepare_apply_workbook(queue, final, report_path)
        assert payload["rows"][0]["reason_code"] == "missing_required_field"

    def test_stale_plan_id_rejection_appears_with_stale_plan_id_reason(
        self, tmp_path: Path
    ) -> None:
        """H3 stale_plan_id rejections surface correctly in the H2 report."""
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row(plan_id="plan-old")])
        payload = prepare_apply_workbook(
            queue, final, report_path,
            allowed_plan_ids=frozenset({"plan-current"}),
        )
        assert payload["rows"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE
        assert payload["rows"][0]["outcome"] == PROMOTION_OUTCOME_REJECTED


# ---------------------------------------------------------------------------
# 5. Mixed workbook — promoted AND rejected
# ---------------------------------------------------------------------------

class TestMixedWorkbookReport:
    def test_rows_accounts_for_all_input_rows(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="auth.failed", plan_id="p1"),         # promoted
            _queue_row(key="nav.home",    status="pending"),     # rejected
            _queue_row(key="profile.name", plan_id="p3"),        # promoted
        ])
        payload = prepare_apply_workbook(queue, final, report_path)

        assert payload["summary"]["total_rows"] == 3
        assert len(payload["rows"]) == 3  # every row accounted for

    def test_rows_order_matches_input_order(self, tmp_path: Path) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="first"),
            _queue_row(key="second", status="pending"),
            _queue_row(key="third"),
        ])
        payload = prepare_apply_workbook(queue, final, report_path)
        keys = [r["key"] for r in payload["rows"]]
        assert keys == ["first", "second", "third"]

    def test_rows_outcomes_match_promotion_decisions(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="a", plan_id="p1"),               # promoted
            _queue_row(key="b", status="pending"),           # rejected
        ])
        payload = prepare_apply_workbook(queue, final, report_path)

        outcomes = {r["key"]: r["outcome"] for r in payload["rows"]}
        assert outcomes["a"] == PROMOTION_OUTCOME_PROMOTED
        assert outcomes["b"] == PROMOTION_OUTCOME_REJECTED

    def test_promoted_count_matches_summary_and_rows(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="a"),
            _queue_row(key="b", status="pending"),
            _queue_row(key="c"),
        ])
        payload = prepare_apply_workbook(queue, final, report_path)

        promoted_in_rows = sum(
            1 for r in payload["rows"] if r["outcome"] == PROMOTION_OUTCOME_PROMOTED
        )
        assert promoted_in_rows == payload["summary"]["accepted_rows"]

    def test_backward_compat_rejections_key_still_contains_only_failures(
        self, tmp_path: Path
    ) -> None:
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="a"),               # promoted
            _queue_row(key="b", status="pending"),  # rejected
        ])
        payload = prepare_apply_workbook(queue, final, report_path)

        # 'rejections' must contain ONLY the rejected row (backward compat)
        assert len(payload["rejections"]) == 1
        assert payload["rejections"][0]["key"] == "b"

    def test_report_addition_does_not_change_promotion_outcome(
        self, tmp_path: Path
    ) -> None:
        """H2 adds reporting; it must not change what gets promoted."""
        queue, final, report_path = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [
            _queue_row(key="a"),
            _queue_row(key="b", status="pending"),
        ])
        payload = prepare_apply_workbook(queue, final, report_path)

        # Only 'a' should be in review_final.xlsx
        from l10n_audit.core.audit_runtime import read_simple_xlsx
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["key"] == "a"
