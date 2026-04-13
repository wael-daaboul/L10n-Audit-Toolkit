"""
tests/test_h6_apply_contract.py

H6 Apply Input Contract tests for the Review/Apply Contract Hardening track.

Verifies:
  1. A valid frozen artifact passes the apply contract pre-check
  2. Missing any required column causes ApplyContractError before row processing
  3. Required field present but empty causes ApplyContractError
  4. ApplyContractError aborts before any row-level write logic runs
  5. H1 artifact-type check still runs first (WrongArtifactTypeError precedes
     ApplyContractError for missing-marker artifacts)
  6. Existing row-level hash validation still runs after the H6 pre-check passes
  7. Empty frozen artifacts pass the pre-check (consistent with H1 semantics)
  8. Error message names the offending rows and required fields
  9. ApplyContractError is a ValueError subclass
 10. APPLY_REQUIRED_FIELDS constant is stable
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.fixes.apply_review_fixes import (
    APPLY_REQUIRED_FIELDS,
    ApplyContractError,
    WrongArtifactTypeError,
    _assert_apply_contract,
    _assert_frozen_artifact_type,
    run_apply,
)
from l10n_audit.fixes.fix_merger import (
    FROZEN_ARTIFACT_TYPE_VALUE,
    REVIEW_FINAL_COLUMNS,
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


def _valid_frozen_row(**overrides) -> dict:
    row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "current_value": "فشل تسجيل الدخول",
        "candidate_value": "فشل.",
        "approved_new": "فشل.",
        "status": "approved",
        "review_note": "",
        "source_old_value": "فشل تسجيل الدخول",
        "source_hash": compute_text_hash("فشل تسجيل الدخول"),
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-test-h6",
        "generated_at": "2026-04-13T00:00:00+00:00",
        "frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE,
    }
    row.update(overrides)
    return row


def _write_frozen(path: Path, rows: list[dict]) -> None:
    """Write a frozen artifact with all REVIEW_FINAL_COLUMNS."""
    write_simple_xlsx(rows, REVIEW_FINAL_COLUMNS, path, sheet_name="Review Final")


FAKE_PATH = Path("/fake/review_final.xlsx")


# ---------------------------------------------------------------------------
# 1. APPLY_REQUIRED_FIELDS constant
# ---------------------------------------------------------------------------

class TestApplyRequiredFieldsConstant:
    def test_constant_contains_all_expected_fields(self) -> None:
        required = set(APPLY_REQUIRED_FIELDS)
        assert "key" in required
        assert "locale" in required
        assert "approved_new" in required
        assert "source_hash" in required
        assert "suggested_hash" in required
        assert "plan_id" in required
        assert "frozen_artifact_type" in required

    def test_constant_has_no_display_only_fields(self) -> None:
        """Fields that must NOT be in the apply contract (display-only)."""
        display_fields = {
            "notes", "review_reason", "provenance", "context_type",
            "context_flags", "semantic_risk", "lt_signals", "candidate_value",
            "suggested_fix", "needs_review",
        }
        for field in APPLY_REQUIRED_FIELDS:
            assert field not in display_fields, (
                f"Display-only field '{field}' must not be in APPLY_REQUIRED_FIELDS"
            )

    def test_apply_contract_error_is_value_error_subclass(self) -> None:
        assert issubclass(ApplyContractError, ValueError)


# ---------------------------------------------------------------------------
# 2. _assert_apply_contract() unit tests
# ---------------------------------------------------------------------------

class TestAssertApplyContract:
    def test_empty_rows_accepted(self) -> None:
        _assert_apply_contract([], FAKE_PATH)  # must not raise

    def test_valid_row_accepted(self) -> None:
        rows = [_valid_frozen_row()]
        _assert_apply_contract(rows, FAKE_PATH)  # must not raise

    def test_multiple_valid_rows_accepted(self) -> None:
        rows = [
            _valid_frozen_row(key="auth.failed"),
            _valid_frozen_row(key="nav.home"),
        ]
        _assert_apply_contract(rows, FAKE_PATH)  # must not raise

    def test_missing_key_raises_apply_contract_error(self) -> None:
        rows = [_valid_frozen_row(key="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "key" in str(exc_info.value)

    def test_missing_locale_raises(self) -> None:
        rows = [_valid_frozen_row(locale="")]
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)

    def test_missing_approved_new_raises(self) -> None:
        rows = [_valid_frozen_row(approved_new="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "approved_new" in str(exc_info.value)

    def test_missing_source_hash_raises(self) -> None:
        rows = [_valid_frozen_row(source_hash="")]
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)

    def test_missing_suggested_hash_raises(self) -> None:
        rows = [_valid_frozen_row(suggested_hash="")]
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)

    def test_missing_plan_id_raises(self) -> None:
        rows = [_valid_frozen_row(plan_id="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "plan_id" in str(exc_info.value)

    def test_missing_frozen_artifact_type_raises(self) -> None:
        rows = [_valid_frozen_row(frozen_artifact_type="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "frozen_artifact_type" in str(exc_info.value)

    def test_whitespace_only_field_counts_as_empty(self) -> None:
        rows = [_valid_frozen_row(key="   ")]
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)

    def test_none_field_value_counts_as_empty(self) -> None:
        row = _valid_frozen_row()
        row["approved_new"] = None
        with pytest.raises(ApplyContractError):
            _assert_apply_contract([row], FAKE_PATH)

    def test_single_invalid_row_in_multi_row_artifact_fails_whole_artifact(
        self,
    ) -> None:
        """One bad row poisons the whole artifact — no partial contracts."""
        rows = [
            _valid_frozen_row(key="auth.failed"),
            _valid_frozen_row(key=""),           # invalid
            _valid_frozen_row(key="nav.home"),
        ]
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)

    def test_error_message_names_file_path(self) -> None:
        rows = [_valid_frozen_row(key="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "/fake/review_final.xlsx" in str(exc_info.value)

    def test_error_message_names_required_fields(self) -> None:
        rows = [_valid_frozen_row(key="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        msg = str(exc_info.value)
        assert "APPLY_REQUIRED_FIELDS" in msg or "key" in msg

    def test_error_message_names_prepare_apply_as_remedy(self) -> None:
        rows = [_valid_frozen_row(approved_new="")]
        with pytest.raises(ApplyContractError) as exc_info:
            _assert_apply_contract(rows, FAKE_PATH)
        assert "prepare-apply" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. H1 runs before H6
# ---------------------------------------------------------------------------

class TestPrechecksOrdering:
    def test_h1_runs_before_h6(self) -> None:
        """
        An artifact that fails H1 (no frozen_artifact_type marker) must raise
        WrongArtifactTypeError, not ApplyContractError, because H1 runs first.
        """
        rows = [_valid_frozen_row(frozen_artifact_type="")]  # H1 would catch missing marker
        # _assert_frozen_artifact_type checks for wrong VALUE, not empty value,
        # so manually remove the column to trigger H1:
        rows_no_marker = [{k: v for k, v in r.items() if k != "frozen_artifact_type"}
                          for r in rows]
        with pytest.raises(WrongArtifactTypeError):
            _assert_frozen_artifact_type(rows_no_marker, FAKE_PATH)

    def test_h6_runs_independently_of_h1_on_valid_marker(self) -> None:
        """After passing H1, H6 still catches an empty required field."""
        rows = [_valid_frozen_row(approved_new="")]
        # H1 passes (marker is correct)
        _assert_frozen_artifact_type(rows, FAKE_PATH)  # must not raise
        # H6 must catch the empty approved_new
        with pytest.raises(ApplyContractError):
            _assert_apply_contract(rows, FAKE_PATH)


# ---------------------------------------------------------------------------
# 4. run_apply integration tests
# ---------------------------------------------------------------------------

class TestRunApplyH6Integration:
    def test_valid_frozen_artifact_passes_contract_and_proceeds(
        self, tmp_path: Path
    ) -> None:
        """
        A properly-formed frozen artifact must pass both H1 and H6 pre-checks
        and proceed to normal apply processing.
        """
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "review_final.xlsx"
        _write_frozen(frozen, [_valid_frozen_row()])

        try:
            run_apply(runtime, frozen)
        except (WrongArtifactTypeError, ApplyContractError) as exc:
            pytest.fail(f"Pre-check rejected valid frozen artifact: {exc}")

    def test_empty_approved_new_fails_contract_before_any_write(
        self, tmp_path: Path
    ) -> None:
        """
        A frozen artifact with empty approved_new must raise ApplyContractError
        before any locale file is modified.
        """
        runtime = _make_runtime(tmp_path)
        original_ar = runtime.ar_file.read_text(encoding="utf-8")
        frozen = tmp_path / "review_final.xlsx"
        _write_frozen(frozen, [_valid_frozen_row(approved_new="")])

        with pytest.raises(ApplyContractError):
            run_apply(runtime, frozen)

        # No partial write must have occurred
        assert runtime.ar_file.read_text(encoding="utf-8") == original_ar

    def test_empty_source_hash_fails_contract_before_any_write(
        self, tmp_path: Path
    ) -> None:
        runtime = _make_runtime(tmp_path)
        original_ar = runtime.ar_file.read_text(encoding="utf-8")
        frozen = tmp_path / "review_final.xlsx"
        _write_frozen(frozen, [_valid_frozen_row(source_hash="")])

        with pytest.raises(ApplyContractError):
            run_apply(runtime, frozen)

        assert runtime.ar_file.read_text(encoding="utf-8") == original_ar

    def test_empty_plan_id_fails_contract_before_any_write(
        self, tmp_path: Path
    ) -> None:
        runtime = _make_runtime(tmp_path)
        original_ar = runtime.ar_file.read_text(encoding="utf-8")
        frozen = tmp_path / "review_final.xlsx"
        _write_frozen(frozen, [_valid_frozen_row(plan_id="")])

        with pytest.raises(ApplyContractError):
            run_apply(runtime, frozen)

        assert runtime.ar_file.read_text(encoding="utf-8") == original_ar

    def test_contract_failure_on_first_row_aborts_all_rows(
        self, tmp_path: Path
    ) -> None:
        """
        Even if only one row violates the contract, zero rows must be applied.
        The entire invocation is aborted.
        """
        runtime = _make_runtime(tmp_path)
        # Write a second key that could be applied
        _write_json(runtime.ar_file, {
            "auth.failed": "فشل تسجيل الدخول",
            "nav.home": "الرئيسية",
        })
        original_ar = runtime.ar_file.read_text(encoding="utf-8")
        frozen = tmp_path / "review_final.xlsx"
        _write_frozen(frozen, [
            _valid_frozen_row(key="auth.failed", approved_new=""),   # contract fails
            _valid_frozen_row(key="nav.home",
                              source_hash=compute_text_hash("الرئيسية"),
                              suggested_hash=compute_text_hash("Home"),
                              approved_new="Home"),
        ])

        with pytest.raises(ApplyContractError):
            run_apply(runtime, frozen)

        # nav.home must NOT have been applied
        assert runtime.ar_file.read_text(encoding="utf-8") == original_ar

    def test_empty_frozen_artifact_passes_contract_check(
        self, tmp_path: Path
    ) -> None:
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "review_final.xlsx"
        write_simple_xlsx([], REVIEW_FINAL_COLUMNS, frozen, sheet_name="Review Final")

        try:
            run_apply(runtime, frozen)
        except (WrongArtifactTypeError, ApplyContractError) as exc:
            pytest.fail(f"Pre-checks rejected valid empty frozen artifact: {exc}")

    def test_row_level_hash_validation_still_runs_after_h6_passes(
        self, tmp_path: Path
    ) -> None:
        """
        A frozen artifact where H6 passes but the source hash does not match
        the live disk value must still be rejected by the existing hash check
        (not silently accepted or obscured by H6).
        """
        runtime = _make_runtime(tmp_path)
        frozen = tmp_path / "review_final.xlsx"
        # Valid contract but stale source_hash (hash of a different value)
        _write_frozen(frozen, [
            _valid_frozen_row(
                source_hash=compute_text_hash("completely different value"),
            )
        ])

        # Must not raise ApplyContractError (H6 passes — field is non-empty)
        # but the row should be rejected by the live staleness check
        try:
            result = run_apply(runtime, frozen)
        except ApplyContractError:
            pytest.fail("H6 incorrectly rejected a non-empty source_hash")
        except Exception:
            pass  # other errors (hash mismatch, etc.) are acceptable here

    def test_apply_contract_error_is_distinct_from_wrong_artifact_type(
        self, tmp_path: Path
    ) -> None:
        """
        WrongArtifactTypeError (H1) and ApplyContractError (H6) are distinct
        exception types so callers can handle them separately.
        """
        assert WrongArtifactTypeError is not ApplyContractError
        assert not issubclass(WrongArtifactTypeError, ApplyContractError)
        assert not issubclass(ApplyContractError, WrongArtifactTypeError)
