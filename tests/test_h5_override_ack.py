"""
tests/test_h5_override_ack.py

H5 Override Acknowledgement tests for the Review/Apply Contract Hardening track.

Verifies:
  1. approved_new == candidate_value (hashes match) → promoted without flag
  2. approved_new != candidate_value, no override_acknowledged field → rejected
  3. approved_new != candidate_value, override_acknowledged = "false" → rejected
  4. approved_new != candidate_value, override_acknowledged = "true" → promoted
  5. override_acknowledged with extra whitespace / mixed case → handled safely
  6. override_acknowledged = "" (empty string) → treated as false → rejected
  7. Absent override_acknowledged column → treated as false → rejected
  8. Correct reason_code (override_not_acknowledged) in rejection record
  9. Rejection details contain approved_hash and suggested_hash
 10. OVERRIDE_NOT_ACK_REASON_CODE constant is stable and distinct
 11. Interaction with H4: both drift and override checks active simultaneously
 12. Interaction with H3: plan_id still enforced before override check
 13. H5 does NOT fire when approved_new == candidate_value (no false positives)
 14. Override accepted row carries the reviewer's approved_new (not candidate_value)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, read_simple_xlsx, write_simple_xlsx
from l10n_audit.fixes.fix_merger import (
    OVERRIDE_NOT_ACK_REASON_CODE,
    REVIEW_FINAL_COLUMNS,
    STALE_PLAN_ID_REASON_CODE,
    prepare_apply_workbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_QUEUE_COLUMNS = [
    "key", "locale", "issue_type", "current_value", "candidate_value",
    "approved_new",
    "status", "review_note", "source_old_value", "source_hash",
    "suggested_hash", "plan_id", "generated_at",
]
_QUEUE_COLUMNS_WITH_ACK = _QUEUE_COLUMNS + ["override_acknowledged"]


def _queue_row(**overrides) -> dict:
    """Build a valid queue row where approved_new == candidate_value."""
    row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "current_value": "فشل تسجيل الدخول",
        "candidate_value": "فشل.",
        "approved_new": "فشل.",  # matches candidate_value — no override
        "status": "approved",
        "review_note": "",
        "source_old_value": "فشل تسجيل الدخول",
        "source_hash": compute_text_hash("فشل تسجيل الدخول"),
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-h5-test",
        "generated_at": "2026-04-13T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict], with_ack_column: bool = False) -> None:
    cols = _QUEUE_COLUMNS_WITH_ACK if with_ack_column else _QUEUE_COLUMNS
    write_simple_xlsx(rows, cols, path, sheet_name="Review Queue")


FAKE_PATH = Path("/fake/review_queue.xlsx")


# ---------------------------------------------------------------------------
# 1. Constant
# ---------------------------------------------------------------------------

class TestOverrideNotAckConstant:
    def test_reason_code_is_stable_string(self) -> None:
        assert OVERRIDE_NOT_ACK_REASON_CODE == "override_not_acknowledged"

    def test_reason_code_is_distinct_from_other_codes(self) -> None:
        other_codes = {
            "missing_required_field",
            "invalid_locale",
            "invalid_status_for_freeze",
            "candidate_value_empty",
            "source_value_mismatch",
            "source_hash_mismatch",
            "suggested_hash_mismatch",
            "stale_plan_id",
            "integrity_drift",
            "machine_source_row_not_found",
            "machine_artifact_unreadable",
            "all_checks_passed",
        }
        assert OVERRIDE_NOT_ACK_REASON_CODE not in other_codes


# ---------------------------------------------------------------------------
# 2. No override (approved_new == candidate_value)
# ---------------------------------------------------------------------------

class TestNoOverrideNeeded:
    def test_approved_equals_candidate_no_flag_required(
        self, tmp_path: Path
    ) -> None:
        """When approved_new matches candidate_value, no acknowledgement needed."""
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        # Row where implied approved_new == candidate_value == "فشل."
        _write_queue(queue, [_queue_row()])
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 0

    def test_h5_does_not_fire_for_matching_approved_new(
        self, tmp_path: Path
    ) -> None:
        """No override_not_acknowledged rejection when hashes match."""
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [_queue_row()], with_ack_column=True)
        payload = prepare_apply_workbook(queue, final, report)
        reason_codes = {r["reason_code"] for r in payload["rejections"]}
        assert OVERRIDE_NOT_ACK_REASON_CODE not in reason_codes


# ---------------------------------------------------------------------------
# 3. Override without acknowledgement → rejected
# ---------------------------------------------------------------------------

class TestOverrideWithoutAck:
    def test_override_without_flag_is_rejected(self, tmp_path: Path) -> None:
        """approved_new differs from candidate_value and no flag → rejected."""
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        # Reviewer changed approved_new to a different value — no ack column
        row = _queue_row()
        row["approved_new"] = "خطأ."          # differs from candidate_value فشل.
        _write_queue(queue, [row])
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 0
        assert payload["rejections"][0]["reason_code"] == OVERRIDE_NOT_ACK_REASON_CODE

    def test_override_with_flag_false_is_rejected(self, tmp_path: Path) -> None:
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = "false"
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["rejections"][0]["reason_code"] == OVERRIDE_NOT_ACK_REASON_CODE

    def test_override_with_empty_flag_is_rejected(self, tmp_path: Path) -> None:
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = ""
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["rejections"][0]["reason_code"] == OVERRIDE_NOT_ACK_REASON_CODE

    def test_override_with_absent_column_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """override_acknowledged column entirely absent → treated as false."""
        row = _queue_row()
        row["approved_new"] = "خطأ."
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        # Write WITHOUT the ack column
        _write_queue(queue, [row], with_ack_column=False)
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["rejections"][0]["reason_code"] == OVERRIDE_NOT_ACK_REASON_CODE

    def test_rejected_row_does_not_enter_frozen_artifact(
        self, tmp_path: Path
    ) -> None:
        row = _queue_row()
        row["approved_new"] = "خطأ."
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row])
        prepare_apply_workbook(queue, final, report)
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert rows == []

    def test_rejection_details_contain_approved_and_suggested_hashes(
        self, tmp_path: Path
    ) -> None:
        row = _queue_row()
        row["approved_new"] = "خطأ."
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row])
        payload = prepare_apply_workbook(queue, final, report)
        details = payload["rejections"][0]["details"]
        assert "approved_hash" in details
        assert "suggested_hash" in details
        assert details["approved_hash"] == compute_text_hash("خطأ.")
        assert details["suggested_hash"] == compute_text_hash("فشل.")


# ---------------------------------------------------------------------------
# 4. Override WITH acknowledgement → promoted
# ---------------------------------------------------------------------------

class TestOverrideWithAck:
    def test_override_with_flag_true_is_accepted(self, tmp_path: Path) -> None:
        """approved_new != candidate_value + override_acknowledged=true → promoted."""
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = "true"
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 0

    def test_override_with_flag_true_whitespace_trimmed(
        self, tmp_path: Path
    ) -> None:
        """Leading/trailing whitespace in 'true' must be trimmed."""
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = "  true  "
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(queue, final, report)
        assert payload["summary"]["accepted_rows"] == 1

    def test_override_flag_case_insensitive_true(
        self, tmp_path: Path
    ) -> None:
        """'TRUE', 'True', 'tRuE' must all be accepted."""
        for variant in ("TRUE", "True", "tRuE"):
            row = _queue_row()
            row["approved_new"] = "خطأ."
            row["override_acknowledged"] = variant
            queue = tmp_path / f"q_{variant}.xlsx"
            final = tmp_path / f"f_{variant}.xlsx"
            report = tmp_path / f"r_{variant}.json"
            _write_queue(queue, [row], with_ack_column=True)
            payload = prepare_apply_workbook(queue, final, report)
            assert payload["summary"]["accepted_rows"] == 1, (
                f"override_acknowledged='{variant}' must be accepted"
            )

    def test_acknowledged_override_row_carries_reviewer_approved_new(
        self, tmp_path: Path
    ) -> None:
        """
        When override is acknowledged, the frozen artifact must carry the
        reviewer's approved_new value, NOT the original candidate_value.
        """
        row = _queue_row()
        row["approved_new"] = "خطأ في الدخول."
        row["override_acknowledged"] = "true"
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        prepare_apply_workbook(queue, final, report)
        frozen = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert len(frozen) == 1
        assert frozen[0]["approved_new"] == "خطأ في الدخول."


# ---------------------------------------------------------------------------
# 5. Interaction with H3 (plan_id still enforced before H5)
# ---------------------------------------------------------------------------

class TestH5InteractionWithH3:
    def test_stale_plan_id_caught_before_override_check(
        self, tmp_path: Path
    ) -> None:
        """H3 runs before H5 — stale plan_id rejection precedes override check."""
        row = _queue_row(plan_id="plan-OLD")
        row["approved_new"] = "خطأ."  # would trigger H5 if reached
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row])
        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-CURRENT"}),
        )
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE

    def test_valid_plan_still_triggers_h5_when_override_not_acked(
        self, tmp_path: Path
    ) -> None:
        """When plan_id is valid (H3 passes), H5 still fires if override not acked."""
        row = _queue_row(plan_id="plan-CURRENT")
        row["approved_new"] = "خطأ."
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row])
        payload = prepare_apply_workbook(
            queue, final, report,
            allowed_plan_ids=frozenset({"plan-CURRENT"}),
        )
        assert payload["rejections"][0]["reason_code"] == OVERRIDE_NOT_ACK_REASON_CODE


# ---------------------------------------------------------------------------
# 6. Interaction with H4 (drift detection)
# ---------------------------------------------------------------------------

class TestH5InteractionWithH4:
    def _write_machine_queue(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"review_queue": rows, "plan_id_source": "report_aggregator"},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_clean_drift_and_acknowledged_override_promotes(
        self, tmp_path: Path
    ) -> None:
        """Both H4 (no drift) and H5 (ack=true) pass → row promoted."""
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = "true"
        machine_row = {
            "key": row["key"], "locale": row["locale"], "plan_id": row["plan_id"],
            "source_hash": row["source_hash"], "suggested_hash": row["suggested_hash"],
            "generated_at": row["generated_at"], "issue_type": row["issue_type"],
            "source_old_value": row["source_old_value"],
        }
        mq = tmp_path / "review_machine_queue.json"
        self._write_machine_queue(mq, [machine_row])
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(
            queue, final, report, machine_queue_path=mq
        )
        assert payload["summary"]["accepted_rows"] == 1

    def test_drift_caught_before_override_check(self, tmp_path: Path) -> None:
        """H4 runs before H5 — integrity drift must be caught first."""
        row = _queue_row()
        row["approved_new"] = "خطأ."
        row["override_acknowledged"] = "true"
        # Machine source has a different source_hash → drift
        machine_row = {
            "key": row["key"], "locale": row["locale"], "plan_id": row["plan_id"],
            "source_hash": "MACHINE_ORIGINAL_HASH",  # differs
            "suggested_hash": row["suggested_hash"],
            "generated_at": row["generated_at"], "issue_type": row["issue_type"],
            "source_old_value": row["source_old_value"],
        }
        mq = tmp_path / "review_machine_queue.json"
        self._write_machine_queue(mq, [machine_row])
        queue, final, report = (
            tmp_path / "q.xlsx", tmp_path / "f.xlsx", tmp_path / "r.json"
        )
        _write_queue(queue, [row], with_ack_column=True)
        payload = prepare_apply_workbook(
            queue, final, report, machine_queue_path=mq
        )
        assert payload["rejections"][0]["reason_code"] == "integrity_drift"
