"""
tests/test_h1_artifact_type_boundary.py

H1 Artifact Type Boundary tests for the Review/Apply Contract Hardening track.

Verifies:
  1. review_final.xlsx produced by prepare_apply_workbook carries the marker
  2. review_queue.xlsx (no marker) is rejected by apply before row processing
  3. A missing marker column causes WrongArtifactTypeError with a clear message
  4. A wrong marker value causes WrongArtifactTypeError with a clear message
  5. A valid frozen artifact passes the artifact-type check and proceeds to hash validation
  6. Empty frozen artifacts (zero rows) are accepted
  7. Legacy frozen artifacts (produced before H1, no marker) are rejected, not silently accepted
  8. Marker text is correct constant string
  9. prepare_apply_workbook stamps frozen_artifact_type on every accepted row
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, read_simple_xlsx, write_simple_xlsx
from l10n_audit.fixes.apply_review_fixes import (
    FROZEN_ARTIFACT_TYPE_COLUMN,
    WrongArtifactTypeError,
    _assert_frozen_artifact_type,
    run_apply,
)
from l10n_audit.fixes.fix_merger import (
    FROZEN_ARTIFACT_TYPE_VALUE,
    REVIEW_FINAL_COLUMNS,
    prepare_apply_workbook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_runtime(tmp_path: Path) -> SimpleNamespace:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    _write_json(en_file, {"auth.failed": "Login failed"})
    _write_json(ar_file, {"auth.failed": "فشل تسجيل الدخول"})
    return SimpleNamespace(
        project_root=tmp_path,
        results_dir=tmp_path / "Results",
        en_file=en_file,
        ar_file=ar_file,
        original_en_file=en_file,
        original_ar_file=ar_file,
        locale_format="json",
        source_locale="en",
        target_locales=("ar",),
        metadata={},
    )


_QUEUE_COLUMNS = [
    "key", "locale", "issue_type", "current_value", "candidate_value",
    "approved_new",          # required by REQUIRED_REVIEW_COLUMNS
    "status", "review_note",
    "source_old_value", "source_hash", "suggested_hash",
    "plan_id", "generated_at",
]

_FROZEN_COLUMNS = _QUEUE_COLUMNS + ["frozen_artifact_type"]


def _queue_row(**overrides) -> dict:
    row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "current_value": "فشل تسجيل الدخول",
        "candidate_value": "فشل.",
        "approved_new": "فشل.",   # required by REQUIRED_REVIEW_COLUMNS
        "status": "approved",
        "review_note": "",
        "source_old_value": "فشل تسجيل الدخول",
        "source_hash": compute_text_hash("فشل تسجيل الدخول"),
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-test-1",
        "generated_at": "2026-04-12T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict]) -> None:
    """Write a review_queue.xlsx — NO frozen_artifact_type marker.
    Includes all columns required by REQUIRED_REVIEW_COLUMNS so that
    read_simple_xlsx does not fail before the artifact-type check.
    """
    write_simple_xlsx(rows, _QUEUE_COLUMNS, path, sheet_name="Review Queue")


def _write_frozen(path: Path, rows: list[dict]) -> None:
    """Write a properly-marked frozen apply artifact."""
    for row in rows:
        row.setdefault("frozen_artifact_type", FROZEN_ARTIFACT_TYPE_VALUE)
    write_simple_xlsx(rows, _FROZEN_COLUMNS, path, sheet_name="Review Final")


# ---------------------------------------------------------------------------
# 1. Constant value correctness
# ---------------------------------------------------------------------------

class TestMarkerConstants:
    def test_frozen_artifact_type_value_is_stable_string(self) -> None:
        assert FROZEN_ARTIFACT_TYPE_VALUE == "frozen_apply_artifact"

    def test_frozen_artifact_type_column_is_stable_string(self) -> None:
        assert FROZEN_ARTIFACT_TYPE_COLUMN == "frozen_artifact_type"

    def test_frozen_artifact_type_column_in_review_final_columns(self) -> None:
        assert "frozen_artifact_type" in REVIEW_FINAL_COLUMNS

    def test_frozen_artifact_type_is_last_column_in_schema(self) -> None:
        assert REVIEW_FINAL_COLUMNS[-1] == "frozen_artifact_type"


# ---------------------------------------------------------------------------
# 2. _assert_frozen_artifact_type() unit tests
# ---------------------------------------------------------------------------

class TestAssertFrozenArtifactType:
    FAKE_PATH = Path("/fake/review_final.xlsx")

    def test_empty_rows_is_accepted(self) -> None:
        """Empty artifact (all rows rejected at promotion) must not raise."""
        _assert_frozen_artifact_type([], self.FAKE_PATH)  # no exception

    def test_valid_marker_is_accepted(self) -> None:
        rows = [{"frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE, "key": "k"}]
        _assert_frozen_artifact_type(rows, self.FAKE_PATH)  # no exception

    def test_multiple_valid_rows_are_accepted(self) -> None:
        rows = [
            {"frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE, "key": "k1"},
            {"frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE, "key": "k2"},
        ]
        _assert_frozen_artifact_type(rows, self.FAKE_PATH)  # no exception

    def test_missing_column_raises_wrong_artifact_type_error(self) -> None:
        rows = [{"key": "k", "source_hash": "abc"}]
        with pytest.raises(WrongArtifactTypeError) as exc_info:
            _assert_frozen_artifact_type(rows, self.FAKE_PATH)
        msg = str(exc_info.value)
        assert "frozen_artifact_type" in msg
        assert "prepare-apply" in msg

    def test_wrong_marker_value_raises_wrong_artifact_type_error(self) -> None:
        rows = [{"frozen_artifact_type": "review_queue", "key": "k"}]
        with pytest.raises(WrongArtifactTypeError) as exc_info:
            _assert_frozen_artifact_type(rows, self.FAKE_PATH)
        msg = str(exc_info.value)
        assert FROZEN_ARTIFACT_TYPE_VALUE in msg
        assert "frozen_artifact_type" in msg

    def test_partial_rows_with_wrong_value_raises(self) -> None:
        """Even a single row with wrong value must fail — whole artifact is tainted."""
        rows = [
            {"frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE, "key": "k1"},
            {"frozen_artifact_type": "WRONG", "key": "k2"},
        ]
        with pytest.raises(WrongArtifactTypeError):
            _assert_frozen_artifact_type(rows, self.FAKE_PATH)

    def test_error_message_includes_file_path(self) -> None:
        rows = [{"key": "k"}]
        with pytest.raises(WrongArtifactTypeError) as exc_info:
            _assert_frozen_artifact_type(rows, self.FAKE_PATH)
        assert "/fake/review_final.xlsx" in str(exc_info.value)

    def test_wrong_artifact_type_error_is_value_error_subclass(self) -> None:
        assert issubclass(WrongArtifactTypeError, ValueError)


# ---------------------------------------------------------------------------
# 3. prepare_apply_workbook stamps the marker
# ---------------------------------------------------------------------------

class TestPrepareApplyStampsMarker:
    def test_accepted_row_carries_frozen_artifact_type(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row()])

        prepare_apply_workbook(queue, final, report)
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

        assert len(rows) == 1
        assert rows[0]["frozen_artifact_type"] == FROZEN_ARTIFACT_TYPE_VALUE

    def test_all_accepted_rows_carry_marker(self, tmp_path: Path) -> None:
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [
            _queue_row(plan_id="p1"),
            _queue_row(plan_id="p2"),
        ])

        prepare_apply_workbook(queue, final, report)
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

        assert len(rows) == 2
        for row in rows:
            assert row["frozen_artifact_type"] == FROZEN_ARTIFACT_TYPE_VALUE

    def test_frozen_artifact_positively_identified(self, tmp_path: Path) -> None:
        """After prepare_apply_workbook, the output passes _assert_frozen_artifact_type."""
        queue = tmp_path / "review_queue.xlsx"
        final = tmp_path / "review_final.xlsx"
        report = tmp_path / "report.json"
        _write_queue(queue, [_queue_row()])

        prepare_apply_workbook(queue, final, report)
        rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

        # Must not raise
        _assert_frozen_artifact_type(rows, final)

    def test_review_queue_not_identifiable_as_frozen(self, tmp_path: Path) -> None:
        """review_queue rows (no marker) must fail _assert_frozen_artifact_type."""
        queue = tmp_path / "review_queue.xlsx"
        _write_queue(queue, [_queue_row()])
        rows = read_simple_xlsx(queue)

        with pytest.raises(WrongArtifactTypeError):
            _assert_frozen_artifact_type(rows, queue)


# ---------------------------------------------------------------------------
# 4. run_apply rejects wrong artifact before row processing
# ---------------------------------------------------------------------------

class TestRunApplyArtifactTypeEnforcement:
    def test_run_apply_rejects_review_queue_without_marker(
        self, tmp_path: Path
    ) -> None:
        """
        Passing review_queue.xlsx directly to run_apply must raise
        WrongArtifactTypeError before any per-row logic runs.
        """
        runtime = _make_runtime(tmp_path)
        review_queue = tmp_path / "review_queue.xlsx"
        _write_queue(review_queue, [_queue_row()])  # no frozen_artifact_type

        with pytest.raises(WrongArtifactTypeError) as exc_info:
            run_apply(runtime, review_queue)

        msg = str(exc_info.value)
        assert "frozen_artifact_type" in msg
        assert "prepare-apply" in msg

    def test_run_apply_error_is_raised_before_locale_write(
        self, tmp_path: Path
    ) -> None:
        """
        WrongArtifactTypeError must be raised before any locale file is touched.
        We verify by checking the locale file is unmodified after the rejection.
        """
        runtime = _make_runtime(tmp_path)
        original_ar_content = runtime.ar_file.read_text(encoding="utf-8")

        review_queue = tmp_path / "wrong_artifact.xlsx"
        _write_queue(review_queue, [_queue_row()])  # no marker

        with pytest.raises(WrongArtifactTypeError):
            run_apply(runtime, review_queue)

        assert runtime.ar_file.read_text(encoding="utf-8") == original_ar_content

    def test_run_apply_accepts_properly_marked_frozen_artifact(
        self, tmp_path: Path
    ) -> None:
        """
        A properly-marked frozen artifact must pass the H1 check and proceed to
        hash validation (which may still reject rows for other reasons).
        """
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "review_final.xlsx"
        # Write a properly-marked frozen row
        _write_frozen(frozen, [_queue_row()])

        # Must not raise WrongArtifactTypeError — may raise other errors or succeed
        try:
            run_apply(runtime, frozen)
        except WrongArtifactTypeError:
            pytest.fail("WrongArtifactTypeError raised on a valid frozen artifact")
        except Exception:
            pass  # other errors (hash mismatch etc.) are acceptable here

    def test_run_apply_accepts_empty_frozen_artifact(
        self, tmp_path: Path
    ) -> None:
        """
        An empty frozen artifact (zero rows) must pass the H1 check.
        Nothing is applied, but no error is raised.
        """
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "review_final.xlsx"
        write_simple_xlsx([], REVIEW_FINAL_COLUMNS, frozen, sheet_name="Review Final")

        try:
            result = run_apply(runtime, frozen)
        except WrongArtifactTypeError:
            pytest.fail("WrongArtifactTypeError raised on empty frozen artifact")

    def test_run_apply_rejects_wrong_marker_value_with_clear_message(
        self, tmp_path: Path
    ) -> None:
        """
        An artifact with frozen_artifact_type = 'WRONG' must be rejected with
        a message that names the expected constant, not a generic error.
        """
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "tampered.xlsx"
        _write_frozen(frozen, [_queue_row(frozen_artifact_type="WRONG")])

        with pytest.raises(WrongArtifactTypeError) as exc_info:
            run_apply(runtime, frozen)

        assert FROZEN_ARTIFACT_TYPE_VALUE in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Legacy artifact compatibility (no silent fallback)
# ---------------------------------------------------------------------------

class TestLegacyArtifactRejection:
    def test_legacy_frozen_artifact_without_marker_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """
        An older review_final.xlsx without frozen_artifact_type (produced before
        H1 hardening) must be rejected, not silently accepted.
        The error message must instruct the user to re-run prepare-apply.
        """
        runtime = _make_runtime(tmp_path)
        # Simulate a legacy frozen artifact: correct content columns but no marker
        legacy_frozen = tmp_path / "review_final.xlsx"
        legacy_row = _queue_row()  # no frozen_artifact_type key
        write_simple_xlsx(
            [legacy_row],
            _QUEUE_COLUMNS,   # deliberately omits frozen_artifact_type
            legacy_frozen,
            sheet_name="Review Final",
        )

        with pytest.raises(WrongArtifactTypeError) as exc_info:
            run_apply(runtime, legacy_frozen)

        msg = str(exc_info.value)
        assert "prepare-apply" in msg, (
            "Error message must tell the user to re-run prepare-apply"
        )
        assert "frozen_artifact_type" in msg

    def test_error_type_is_wrong_artifact_type_not_generic_runtime(
        self, tmp_path: Path
    ) -> None:
        """
        The artifact type rejection must be WrongArtifactTypeError, not a generic
        RuntimeError or ValueError, so callers can handle it specifically.
        """
        runtime = _make_runtime(tmp_path)
        wrong = tmp_path / "review_queue.xlsx"
        _write_queue(wrong, [_queue_row()])

        with pytest.raises(WrongArtifactTypeError):
            run_apply(runtime, wrong)
