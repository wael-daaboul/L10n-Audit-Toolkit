"""
tests/test_h4_integrity_drift.py

H4 Integrity Drift Detection tests for the Review/Apply Contract Hardening track.

Verifies:
  1. Rows whose immutable fields match the machine queue are promoted
  2. Rows with a drifted immutable field (source_hash) are rejected
  3. Rows with multiple drifted fields are rejected with all fields named
  4. Human-editable fields (approved_new, status, review_note) do NOT trigger drift
  5. Missing machine artifact → all rows rejected with machine_artifact_unreadable
  6. Malformed machine artifact (bad JSON) → all rows rejected with machine_artifact_unreadable
  7. Malformed machine artifact (missing 'review_queue' key) → machine_artifact_unreadable
  8. Unmatched row (no machine counterpart) → machine_source_row_not_found
  9. machine_queue_path=None → no drift check, backward-compat
 10. H4 check runs after H3 (stale plan_id caught before machine lookup)
 11. H2 promotion report records drift rejections in 'rows' list
 12. Rejection details name the drifted field(s) specifically
 13. Constants are stable strings
 14. H4_IMMUTABLE_FIELDS does not include human-editable fields
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.fixes.fix_merger import (
    H4_IMMUTABLE_FIELDS,
    INTEGRITY_DRIFT_REASON_CODE,
    MACHINE_ARTIFACT_UNREADABLE_REASON_CODE,
    MACHINE_SOURCE_NOT_FOUND_REASON_CODE,
    PROMOTION_OUTCOME_REJECTED,
    REVIEW_FINAL_COLUMNS,
    STALE_PLAN_ID_REASON_CODE,
    _check_integrity_drift,
    _load_machine_queue_index,
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
        "plan_id": "plan-h4-test",
        "generated_at": "2026-04-13T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _machine_row(**overrides) -> dict:
    """Machine queue row — mirrors the queue row before human edits."""
    row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "source_old_value": "فشل تسجيل الدخول",
        "source_hash": compute_text_hash("فشل تسجيل الدخول"),
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-h4-test",
        "generated_at": "2026-04-13T00:00:00+00:00",
        # Human-editable fields present in machine row (initial pipeline state)
        "approved_new": "فشل.",
        "status": "pending",
        "review_note": "",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict]) -> None:
    write_simple_xlsx(rows, _QUEUE_COLUMNS, path, sheet_name="Review Queue")


def _write_machine_queue(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"review_queue": rows, "plan_id_source": "report_aggregator"},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------

class TestH4Constants:
    def test_integrity_drift_reason_code_is_stable(self) -> None:
        assert INTEGRITY_DRIFT_REASON_CODE == "integrity_drift"

    def test_machine_source_not_found_reason_code_is_stable(self) -> None:
        assert MACHINE_SOURCE_NOT_FOUND_REASON_CODE == "machine_source_row_not_found"

    def test_machine_artifact_unreadable_reason_code_is_stable(self) -> None:
        assert MACHINE_ARTIFACT_UNREADABLE_REASON_CODE == "machine_artifact_unreadable"

    def test_immutable_fields_contains_required_entries(self) -> None:
        required = {"key", "locale", "plan_id", "source_hash", "suggested_hash",
                    "generated_at", "issue_type", "source_old_value"}
        assert required <= set(H4_IMMUTABLE_FIELDS)

    def test_immutable_fields_excludes_human_editable_fields(self) -> None:
        human_editable = {"approved_new", "status", "review_note"}
        for field in human_editable:
            assert field not in H4_IMMUTABLE_FIELDS, (
                f"Human-editable field '{field}' must NOT be in H4_IMMUTABLE_FIELDS"
            )

    def test_all_reason_codes_are_distinct(self) -> None:
        codes = {
            INTEGRITY_DRIFT_REASON_CODE,
            MACHINE_SOURCE_NOT_FOUND_REASON_CODE,
            MACHINE_ARTIFACT_UNREADABLE_REASON_CODE,
        }
        assert len(codes) == 3


# ---------------------------------------------------------------------------
# 2. _load_machine_queue_index() unit tests
# ---------------------------------------------------------------------------

class TestLoadMachineQueueIndex:
    def test_valid_machine_queue_is_indexed(self, tmp_path: Path) -> None:
        mq = tmp_path / "review_machine_queue.json"
        _write_machine_queue(mq, [_machine_row()])
        index = _load_machine_queue_index(mq)
        assert ("auth.failed", "ar", "plan-h4-test") in index

    def test_index_key_is_key_locale_plan_id_tuple(self, tmp_path: Path) -> None:
        mq = tmp_path / "review_machine_queue.json"
        _write_machine_queue(mq, [_machine_row(key="k1", locale="ar", plan_id="p1")])
        index = _load_machine_queue_index(mq)
        assert ("k1", "ar", "p1") in index

    def test_malformed_json_raises_value_error(self, tmp_path: Path) -> None:
        mq = tmp_path / "bad.json"
        mq.write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot read machine queue"):
            _load_machine_queue_index(mq)

    def test_missing_review_queue_key_raises_value_error(self, tmp_path: Path) -> None:
        mq = tmp_path / "bad.json"
        mq.write_text(json.dumps({"wrong_key": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="unexpected structure"):
            _load_machine_queue_index(mq)

    def test_review_queue_not_list_raises_value_error(self, tmp_path: Path) -> None:
        mq = tmp_path / "bad.json"
        mq.write_text(json.dumps({"review_queue": "not a list"}), encoding="utf-8")
        with pytest.raises(ValueError):
            _load_machine_queue_index(mq)


# ---------------------------------------------------------------------------
# 3. _check_integrity_drift() unit tests
# ---------------------------------------------------------------------------

class TestCheckIntegrityDrift:
    def test_identical_rows_produce_no_drift(self) -> None:
        row = _machine_row()
        assert _check_integrity_drift(row, row) == []

    def test_drifted_source_hash_is_detected(self) -> None:
        workbook = _machine_row(source_hash="TAMPERED_HASH")
        machine = _machine_row()
        drifted = _check_integrity_drift(workbook, machine)
        assert any(d["field"] == "source_hash" for d in drifted)

    def test_drifted_suggested_hash_is_detected(self) -> None:
        workbook = _machine_row(suggested_hash="DIFFERENT")
        machine = _machine_row()
        drifted = _check_integrity_drift(workbook, machine)
        assert any(d["field"] == "suggested_hash" for d in drifted)

    def test_multiple_drifted_fields_all_reported(self) -> None:
        workbook = _machine_row(source_hash="A", suggested_hash="B")
        machine = _machine_row()
        drifted = _check_integrity_drift(workbook, machine)
        drifted_names = {d["field"] for d in drifted}
        assert "source_hash" in drifted_names
        assert "suggested_hash" in drifted_names

    def test_drift_record_contains_both_values(self) -> None:
        workbook = _machine_row(source_hash="WORKBOOK_VALUE")
        machine = _machine_row(source_hash="MACHINE_VALUE")
        drifted = _check_integrity_drift(workbook, machine)
        sh = next(d for d in drifted if d["field"] == "source_hash")
        assert sh["workbook_value"] == "WORKBOOK_VALUE"
        assert sh["machine_value"] == "MACHINE_VALUE"

    def test_changed_approved_new_does_not_trigger_drift(self) -> None:
        """approved_new is human-editable — changing it must not count as drift."""
        workbook = _machine_row(approved_new="HUMAN_APPROVED")
        machine = _machine_row(approved_new="pipeline_original")
        assert _check_integrity_drift(workbook, machine) == []

    def test_changed_status_does_not_trigger_drift(self) -> None:
        workbook = _machine_row(status="approved")
        machine = _machine_row(status="pending")
        assert _check_integrity_drift(workbook, machine) == []

    def test_changed_review_note_does_not_trigger_drift(self) -> None:
        workbook = _machine_row(review_note="LGTM")
        machine = _machine_row(review_note="")
        assert _check_integrity_drift(workbook, machine) == []


# ---------------------------------------------------------------------------
# 4. prepare_apply_workbook integration (machine_queue_path=None → no check)
# ---------------------------------------------------------------------------

class TestNoDriftCheckWhenMachinePathOmitted:
    def test_existing_callers_unaffected_without_machine_queue_path(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(queue, final, report_path)
        assert payload["summary"]["accepted_rows"] == 1

    def test_no_drift_rejection_when_machine_path_none(
        self, tmp_path: Path
    ) -> None:
        """Even a 'tampered' row promotes fine when machine_queue_path is None."""
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        _write_queue(queue, [_queue_row(source_hash="TAMPERED")])

        # No machine path — row fails source_hash_mismatch (existing check),
        # NOT integrity_drift.
        payload = prepare_apply_workbook(queue, final, report_path)
        reason_codes = {r["reason_code"] for r in payload["rejections"]}
        assert INTEGRITY_DRIFT_REASON_CODE not in reason_codes


# ---------------------------------------------------------------------------
# 5. Successful promotion with matching machine queue
# ---------------------------------------------------------------------------

class TestSuccessfulPromotionWithMachineQueue:
    def test_matching_row_is_promoted(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row()])
        _write_machine_queue(mq, [_machine_row()])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 0

    def test_changed_approved_new_does_not_block_promotion(
        self, tmp_path: Path
    ) -> None:
        """Reviewer changed approved_new — this is the expected human edit."""
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        # Workbook has reviewer-changed approved_new; machine row has original
        _write_queue(queue, [_queue_row()])
        _write_machine_queue(mq, [_machine_row(approved_new="ORIGINAL_PIPELINE")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        # No integrity_drift rejection — approved_new is editable
        drift_rejections = [
            r for r in payload["rejections"]
            if r["reason_code"] == INTEGRITY_DRIFT_REASON_CODE
        ]
        assert len(drift_rejections) == 0


# ---------------------------------------------------------------------------
# 6. Drift-triggered rejections
# ---------------------------------------------------------------------------

class TestDriftTriggersRejection:
    def test_tampered_source_hash_causes_integrity_drift_rejection(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        # Workbook row has a tampered source_hash that still matches itself
        # (so existing hash-vs-current-value check passes) but differs from machine
        original_hash = compute_text_hash("فشل تسجيل الدخول")
        _write_queue(queue, [_queue_row()])  # correct source_hash
        # Machine row has a DIFFERENT source_hash (simulating the swap)
        _write_machine_queue(mq, [_machine_row(source_hash="MACHINE_ORIGINAL_HASH")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        assert payload["summary"]["accepted_rows"] == 0
        assert payload["rejections"][0]["reason_code"] == INTEGRITY_DRIFT_REASON_CODE

    def test_drifted_row_does_not_enter_frozen_artifact(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row()])
        _write_machine_queue(mq, [_machine_row(source_hash="DIFFERENT")])

        prepare_apply_workbook(queue, final, report_path, machine_queue_path=mq)

        from l10n_audit.core.audit_runtime import read_simple_xlsx
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert rows == []

    def test_rejection_details_name_drifted_fields(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row()])
        _write_machine_queue(mq, [_machine_row(source_hash="DIFF1", suggested_hash="DIFF2")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        rejection = payload["rejections"][0]
        assert rejection["reason_code"] == INTEGRITY_DRIFT_REASON_CODE
        drifted_names = {d["field"] for d in rejection["details"]["drifted_fields"]}
        assert "source_hash" in drifted_names
        assert "suggested_hash" in drifted_names

    def test_drift_rejection_appears_in_h2_rows_with_correct_outcome(
        self, tmp_path: Path
    ) -> None:
        """H2 promotion report must correctly record the drift rejection."""
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row()])
        _write_machine_queue(mq, [_machine_row(source_hash="DIFF")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        assert payload["rows"][0]["outcome"] == PROMOTION_OUTCOME_REJECTED
        assert payload["rows"][0]["reason_code"] == INTEGRITY_DRIFT_REASON_CODE

    def test_mixed_rows_clean_promoted_drifted_rejected(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [
            _queue_row(key="auth.failed"),
            _queue_row(key="nav.home"),
        ])
        _write_machine_queue(mq, [
            _machine_row(key="auth.failed"),          # clean
            _machine_row(key="nav.home", source_hash="TAMPERED"),  # drifted
        ])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        assert payload["summary"]["accepted_rows"] == 1
        assert payload["summary"]["rejected_rows"] == 1
        outcomes = {r["key"]: r["reason_code"] for r in payload["rows"]}
        assert outcomes["auth.failed"] == "all_checks_passed"
        assert outcomes["nav.home"] == INTEGRITY_DRIFT_REASON_CODE


# ---------------------------------------------------------------------------
# 7. Unmatched rows
# ---------------------------------------------------------------------------

class TestUnmatchedRows:
    def test_row_with_no_machine_counterpart_is_rejected(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row(key="unknown.key")])
        _write_machine_queue(mq, [_machine_row(key="auth.failed")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        assert payload["summary"]["accepted_rows"] == 0
        assert payload["rejections"][0]["reason_code"] == MACHINE_SOURCE_NOT_FOUND_REASON_CODE

    def test_unmatched_rejection_details_include_identity(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row(key="ghost.key")])
        _write_machine_queue(mq, [])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=mq,
        )
        rejection = payload["rejections"][0]
        assert rejection["reason_code"] == MACHINE_SOURCE_NOT_FOUND_REASON_CODE
        assert "identity" in rejection["details"]


# ---------------------------------------------------------------------------
# 8. Missing and malformed machine artifact
# ---------------------------------------------------------------------------

class TestMachineArtifactErrors:
    def test_missing_machine_file_rejects_all_rows(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        nonexistent = tmp_path / "does_not_exist.json"
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=nonexistent,
        )
        assert payload["summary"]["accepted_rows"] == 0
        assert payload["rejections"][0]["reason_code"] == MACHINE_ARTIFACT_UNREADABLE_REASON_CODE

    def test_malformed_json_rejects_all_rows(self, tmp_path: Path) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        bad_mq = tmp_path / "bad.json"
        bad_mq.write_text("NOT VALID JSON", encoding="utf-8")
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=bad_mq,
        )
        assert payload["summary"]["accepted_rows"] == 0
        assert payload["rejections"][0]["reason_code"] == MACHINE_ARTIFACT_UNREADABLE_REASON_CODE

    def test_malformed_structure_missing_review_queue_key(
        self, tmp_path: Path
    ) -> None:
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        bad_mq = tmp_path / "bad.json"
        bad_mq.write_text(json.dumps({"wrong": []}), encoding="utf-8")
        _write_queue(queue, [_queue_row()])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=bad_mq,
        )
        assert payload["rejections"][0]["reason_code"] == MACHINE_ARTIFACT_UNREADABLE_REASON_CODE

    def test_missing_artifact_does_not_silently_promote_rows(
        self, tmp_path: Path
    ) -> None:
        """Critically: missing machine artifact must NOT silently let rows through."""
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        nonexistent = tmp_path / "nope.json"
        _write_queue(queue, [_queue_row()])

        prepare_apply_workbook(
            queue, final, report_path,
            machine_queue_path=nonexistent,
        )

        from l10n_audit.core.audit_runtime import read_simple_xlsx
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
        assert rows == [], (
            "Missing machine artifact must not silently promote rows into review_final.xlsx"
        )


# ---------------------------------------------------------------------------
# 9. H4 runs after H3 (ordering)
# ---------------------------------------------------------------------------

class TestH4RunsAfterH3:
    def test_stale_plan_id_caught_before_machine_lookup(
        self, tmp_path: Path
    ) -> None:
        """
        A row with stale plan_id should be rejected with stale_plan_id,
        not machine_source_row_not_found — H3 runs first.
        """
        queue = tmp_path / "q.xlsx"
        final = tmp_path / "f.xlsx"
        report_path = tmp_path / "r.json"
        mq = tmp_path / "review_machine_queue.json"
        _write_queue(queue, [_queue_row(plan_id="plan-OLD")])
        _write_machine_queue(mq, [_machine_row(plan_id="plan-CURRENT")])

        payload = prepare_apply_workbook(
            queue, final, report_path,
            allowed_plan_ids=frozenset({"plan-CURRENT"}),
            machine_queue_path=mq,
        )
        assert payload["rejections"][0]["reason_code"] == STALE_PLAN_ID_REASON_CODE
