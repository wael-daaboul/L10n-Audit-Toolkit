"""
tests/test_h3_plan_id_cross_check.py

H3 Plan-ID Cross-Check tests for the Review/Apply Contract Hardening track.

Verifies:
  1. A row with valid plan_id is still promotable when allowed_plan_ids is set
  2. A row with a mismatched (stale) plan_id is rejected at promotion
  3. A row with a missing/empty plan_id is rejected (existing missing_required_field
     check, not plan_id cross-check — this ensures correct reason ordering)
  4. The stale_plan_id reason_code is distinguishable from other rejection reasons
  5. When allowed_plan_ids is None (default), no plan cross-check runs — all
     existing callers are backward-compatible
  6. Mixed workbooks: correct-plan rows promoted, stale-plan rows rejected
  7. Single-plan constraint: rows from exactly that plan pass
  8. Empty allowed_plan_ids frozenset rejects every row (edge case)
  9. Multiple allowed plan_ids: any matching plan is accepted
 10. Rejection record includes the row's plan_id and the allowed set in its details
 11. CLI caller (cmd_prepare_apply) derives and passes allowed_plan_ids from the
     machine queue artifact written by the last run (H3 end-to-end wiring)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, read_simple_xlsx, write_simple_xlsx
from l10n_audit.fixes.fix_merger import (
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
        "plan_id": "plan-current",
        "generated_at": "2026-04-12T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict]) -> None:
    write_simple_xlsx(rows, _QUEUE_COLUMNS, path, sheet_name="Review Queue")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. STALE_PLAN_ID_REASON_CODE constant
# ---------------------------------------------------------------------------

class TestPlanIdReasonCode:
    def test_stale_plan_id_reason_code_is_stable_string(self) -> None:
        assert STALE_PLAN_ID_REASON_CODE == "stale_plan_id"

    def test_stale_plan_id_reason_code_is_distinct_from_other_reason_codes(self) -> None:
        """Reason code must be unique so callers can match on it specifically."""
        other_codes = {
            "missing_required_field",
            "invalid_locale",
            "invalid_status_for_freeze",
            "candidate_value_empty",
            "source_value_mismatch",
            "source_hash_mismatch",
            "suggested_hash_mismatch",
            "invalid_row_shape",
        }
        assert STALE_PLAN_ID_REASON_CODE not in other_codes


# ---------------------------------------------------------------------------
# 2. Backward compatibility: allowed_plan_ids=None means no plan check
# ---------------------------------------------------------------------------

class TestNoPlanConstraint:
    """When allowed_plan_ids is not provided (None), all existing behavior unchanged."""

    def test_no_allowed_plan_ids_accepts_any_valid_plan(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="any-plan-42")])

        payload = prepare_apply_workbook(queue, final, report)
        # No plan constraint — row must be promoted
        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 0

    def test_no_allowed_plan_ids_accepts_multiple_different_plans(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="plan-A", key="auth.failed"),
            _queue_row(plan_id="plan-B", key="profile.name"),
        ])

        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 2

    def test_existing_tests_unaffected_by_default_parameter(
        self, tmp_path: Path
    ) -> None:
        """Call with three positional args — same as all existing callers."""
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 1


# ---------------------------------------------------------------------------
# 3. Single-plan constraint
# ---------------------------------------------------------------------------

class TestSinglePlanConstraint:
    """allowed_plan_ids with one plan_id — only matching rows are promoted."""

    def test_matching_plan_id_is_promoted(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="plan-current")])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 0

    def test_stale_plan_id_is_rejected(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="plan-old")])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        assert payload["summary"]["accepted_rows"] == 0
        assert payload["summary"]["rejected_rows"] == 1
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE

    def test_stale_row_does_not_enter_frozen_artifact(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="plan-old")])

        prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert rows == [], "Stale-plan row must not enter review_final.xlsx"

    def test_rejection_record_names_row_plan_and_allowed_set(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="plan-OLD")])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-CURRENT"}),
        )

        rejection = payload["rejections"][0]
        assert rejection["reason_code"] == STALE_PLAN_ID_REASON_CODE
        assert rejection["details"]["row_plan_id"] == "plan-OLD"
        assert "plan-CURRENT" in rejection["details"]["allowed_plan_ids"]

    def test_stale_reason_code_is_distinguishable_from_hash_mismatch(
        self, tmp_path: Path
    ) -> None:
        """A stale-plan rejection must have a different reason_code than
        source_hash_mismatch so callers can distinguish them."""
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_stale = tmp_path / "report_stale.json"
        report_hash = tmp_path / "report_hash.json"

        _write_queue(queue, [_queue_row(plan_id="plan-old")])
        payload_stale = prepare_apply_workbook(
            queue, final, report_stale,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        _write_queue(
            tmp_path / "q2.xlsx",
            [_queue_row(source_hash=compute_text_hash("DIFFERENT"))],
        )
        payload_hash = prepare_apply_workbook(
            tmp_path / "q2.xlsx", final, report_hash,
        )

        stale_codes = {r["reason_code"] for r in payload_stale["rejections"]}
        hash_codes = {r["reason_code"] for r in payload_hash["rejections"]}
        assert stale_codes != hash_codes
        assert STALE_PLAN_ID_REASON_CODE in stale_codes
        assert "source_hash_mismatch" in hash_codes


# ---------------------------------------------------------------------------
# 4. Mixed workbook: correct + stale plan rows
# ---------------------------------------------------------------------------

class TestMixedPlanWorkbook:
    def test_correct_plan_rows_promoted_stale_rows_rejected(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="plan-current", key="auth.failed"),
            _queue_row(plan_id="plan-old",     key="profile.name"),
            _queue_row(plan_id="plan-current", key="nav.home"),
        ])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        assert payload["summary"]["accepted_rows"] == 2
        assert payload["summary"]["rejected_rows"] == 1
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE

    def test_promoted_rows_all_have_correct_plan_id(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="plan-current", key="auth.failed"),
            _queue_row(plan_id="plan-stale",   key="profile.name"),
        ])

        prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert len(rows) == 1
        assert rows[0]["plan_id"] == "plan-current"


# ---------------------------------------------------------------------------
# 5. Multiple allowed plan IDs
# ---------------------------------------------------------------------------

class TestMultipleAllowedPlans:
    def test_both_plans_in_allowed_set_are_promoted(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="plan-A", key="auth.failed"),
            _queue_row(plan_id="plan-B", key="profile.name"),
        ])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-A", "plan-B"}),
        )

        assert payload["summary"]["accepted_rows"] == 2

    def test_third_plan_not_in_allowed_set_is_rejected(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="plan-A",   key="auth.failed"),
            _queue_row(plan_id="plan-C",   key="profile.name"),
        ])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-A", "plan-B"}),
        )

        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 1
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE


# ---------------------------------------------------------------------------
# 6. Empty allowed_plan_ids set rejects everything
# ---------------------------------------------------------------------------

class TestEmptyAllowedPlanIds:
    def test_empty_frozenset_rejects_all_rows(self, tmp_path: Path) -> None:
        """frozenset() means no plan is valid — every row is stale."""
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="plan-current")])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset(),
        )

        assert payload["summary"]["accepted_rows"] == 0
        assert payload["summary"]["rejected_rows"] == 1
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE


# ---------------------------------------------------------------------------
# 7. Empty plan_id in row — existing missing_required_field fires first
# ---------------------------------------------------------------------------

class TestMissingPlanId:
    def test_empty_plan_id_raises_missing_required_field_not_stale(
        self, tmp_path: Path
    ) -> None:
        """
        A row with an empty plan_id must be rejected with missing_required_field,
        not stale_plan_id.  The empty-string check runs before the plan cross-check.
        """
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="")])

        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-current"}),
        )

        assert payload["summary"]["rejected_rows"] == 1
        rejection = payload["rejections"][0]
        assert rejection["reason_code"] == "missing_required_field"
        assert rejection["details"]["field"] == "plan_id"

    def test_empty_plan_id_rejected_even_without_plan_constraint(
        self, tmp_path: Path
    ) -> None:
        """Empty plan_id is already rejected by the existing required-field check."""
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row(plan_id="")])

        payload = prepare_apply_workbook(queue, final, report)

        assert payload["summary"]["rejected_rows"] == 1
        assert payload["rejections"][0]["reason_code"] == "missing_required_field"


# ---------------------------------------------------------------------------
# 8. CLI caller (cmd_prepare_apply) end-to-end H3 wiring
# ---------------------------------------------------------------------------


class TestCliCallerH3Wiring:
    """Verify that cmd_prepare_apply now derives and passes allowed_plan_ids
    from the machine queue artifact (end-to-end H3 wiring)."""

    def test_cli_passes_allowed_plan_ids_from_machine_queue(
        self, tmp_path: Path
    ) -> None:
        """When review_machine_queue.json exists, cmd_prepare_apply passes the
        plan_ids found there as allowed_plan_ids to prepare_apply_workbook."""
        from l10n_audit.core.cli import cmd_prepare_apply

        machine_queue_content = json.dumps({
            "review_queue": [
                {"plan_id": "plan-run1-a", "key": "k1"},
                {"plan_id": "plan-run1-b", "key": "k2"},
            ],
            "plan_id_source": "report_aggregator",
        })

        def fake_exists(self):
            return True

        def fake_read_text(self, encoding="utf-8"):
            if "review_machine_queue" in str(self):
                return machine_queue_content
            raise OSError("not the machine queue")

        args = argparse.Namespace(
            path=".", review_queue=None, out_final=None, rejection_report=None
        )
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")

        with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
             patch("l10n_audit.core.audit_runtime.load_runtime", return_value=mock_runtime), \
             patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
             patch("pathlib.Path.exists", fake_exists), \
             patch("pathlib.Path.read_text", fake_read_text):

            mock_prepare.return_value = {
                "summary": {"total_rows": 2, "accepted_rows": 2, "rejected_rows": 0}
            }
            result = cmd_prepare_apply(args)

        assert result == 0
        _, kwargs = mock_prepare.call_args
        assert kwargs.get("allowed_plan_ids") == frozenset({"plan-run1-a", "plan-run1-b"})

    def test_cli_falls_back_to_none_when_machine_queue_absent(
        self, tmp_path: Path
    ) -> None:
        """When review_machine_queue.json is absent, cmd_prepare_apply passes
        allowed_plan_ids=None (backward compatible, no plan constraint)."""
        from l10n_audit.core.cli import cmd_prepare_apply

        def fake_exists(self):
            return "review_queue.xlsx" in str(self) and "review_machine_queue" not in str(self)

        args = argparse.Namespace(
            path=".", review_queue=None, out_final=None, rejection_report=None
        )
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")

        with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
             patch("l10n_audit.core.audit_runtime.load_runtime", return_value=mock_runtime), \
             patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
             patch("pathlib.Path.exists", fake_exists):

            mock_prepare.return_value = {
                "summary": {"total_rows": 1, "accepted_rows": 1, "rejected_rows": 0}
            }
            result = cmd_prepare_apply(args)

        assert result == 0
        _, kwargs = mock_prepare.call_args
        assert kwargs.get("allowed_plan_ids") is None

    def test_cli_stale_rows_rejected_in_real_promote_path(
        self, tmp_path: Path
    ) -> None:
        """Integration: cmd_prepare_apply rejects stale-plan rows through the
        real prepare_apply_workbook — not just in unit tests of fix_merger."""
        from l10n_audit.core.cli import cmd_prepare_apply
        from l10n_audit.core.artifact_resolver import resolve_review_machine_queue_json_path

        current_plan = "plan-current-run"
        stale_plan = "plan-old-run"

        # Write review_queue.xlsx with one current and one stale row
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        rejection = tmp_path / "rejection_report.json"
        _write_queue(queue, [
            _queue_row(plan_id=current_plan, key="auth.failed"),
            _queue_row(plan_id=stale_plan,   key="profile.name"),
        ])

        # Write review_machine_queue.json with only the current plan
        machine_dir = tmp_path / "review"
        machine_dir.mkdir(parents=True, exist_ok=True)
        machine_queue_path = machine_dir / "review_machine_queue.json"
        machine_queue_path.write_text(json.dumps({
            "review_queue": [{
                "plan_id": current_plan,
                "key": "auth.failed",
                "locale": "ar",
                "issue_type": "locale_qc",
                "source_old_value": "\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
                "source_hash": compute_text_hash("\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644"),
                "suggested_hash": compute_text_hash("\u0641\u0634\u0644."),
                "generated_at": "2026-04-12T00:00:00+00:00",
            }],
            "plan_id_source": "report_aggregator",
        }), encoding="utf-8")

        args = argparse.Namespace(
            path=".",
            review_queue=str(queue),
            out_final=str(final),
            rejection_report=str(rejection),
        )
        mock_runtime = MagicMock()
        mock_runtime.results_dir = tmp_path
        mock_runtime.project_root = tmp_path

        with patch("l10n_audit.core.cli.find_project_root", return_value=tmp_path), \
             patch("l10n_audit.core.audit_runtime.load_runtime", return_value=mock_runtime):
            result = cmd_prepare_apply(args)

        assert result == 0
        report_data = json.loads(rejection.read_text(encoding="utf-8"))
        assert report_data["summary"]["accepted_rows"] == 1
        assert report_data["summary"]["rejected_rows"] == 1
        assert report_data["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE
        assert report_data["rejections"][0]["plan_id"] == stale_plan

        # Verify frozen artifact only contains the current-plan row
        frozen_rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert len(frozen_rows) == 1
        assert frozen_rows[0]["plan_id"] == current_plan

    def test_cli_valid_rows_still_promote_with_plan_constraint(
        self, tmp_path: Path
    ) -> None:
        """Rows from the current run are not accidentally rejected when
        allowed_plan_ids is active."""
        from l10n_audit.core.cli import cmd_prepare_apply

        current_plan = "plan-valid"
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        rejection = tmp_path / "rejection_report.json"
        _write_queue(queue, [
            _queue_row(plan_id=current_plan, key="auth.failed"),
            _queue_row(plan_id=current_plan, key="nav.home"),
        ])

        machine_dir = tmp_path / "review"
        machine_dir.mkdir(parents=True, exist_ok=True)
        machine_queue_path = machine_dir / "review_machine_queue.json"
        machine_queue_path.write_text(json.dumps({
            "review_queue": [
                {
                    "plan_id": current_plan,
                    "key": "auth.failed",
                    "locale": "ar",
                    "issue_type": "locale_qc",
                    "source_old_value": "\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
                    "source_hash": compute_text_hash("\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644"),
                    "suggested_hash": compute_text_hash("\u0641\u0634\u0644."),
                    "generated_at": "2026-04-12T00:00:00+00:00",
                },
                {
                    "plan_id": current_plan,
                    "key": "nav.home",
                    "locale": "ar",
                    "issue_type": "locale_qc",
                    "source_old_value": "\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
                    "source_hash": compute_text_hash("\u0641\u0634\u0644 \u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644"),
                    "suggested_hash": compute_text_hash("\u0641\u0634\u0644."),
                    "generated_at": "2026-04-12T00:00:00+00:00",
                },
            ],
            "plan_id_source": "report_aggregator",
        }), encoding="utf-8")

        args = argparse.Namespace(
            path=".",
            review_queue=str(queue),
            out_final=str(final),
            rejection_report=str(rejection),
        )
        mock_runtime = MagicMock()
        mock_runtime.results_dir = tmp_path
        mock_runtime.project_root = tmp_path

        with patch("l10n_audit.core.cli.find_project_root", return_value=tmp_path), \
             patch("l10n_audit.core.audit_runtime.load_runtime", return_value=mock_runtime):
            result = cmd_prepare_apply(args)

        assert result == 0
        report_data = json.loads(rejection.read_text(encoding="utf-8"))
        assert report_data["summary"]["accepted_rows"] == 2
        assert report_data["summary"]["rejected_rows"] == 0
