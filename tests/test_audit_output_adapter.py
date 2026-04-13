"""
tests/test_audit_output_adapter.py
===================================

Phase 7C Slice 1 — focused tests for the AuditOutputAdapter.

Covers:
  1.  normalize_audit_finding() maps ``old`` → ``detected_value``
  2.  normalize_audit_finding() maps ``new`` → ``candidate_value``
  3.  adapter injects ``audit_source`` when absent
  4.  adapter injects ``locale`` when absent
  5.  adapter injects ``audit_source`` with provided value when present in row
  6.  unknown extra fields are preserved in ``_raw_metadata``
  7.  ``current_value`` is never emitted
  8.  ``candidate_value`` is present as empty string when no suggestion exists
  9.  ``severity`` defaults to ``"medium"`` when absent from raw row
  10. ``fix_mode`` defaults to ``"review_required"`` when absent
  11. Standard downstream-known fields pass through untouched
  12. ``en_locale_qc.run_stage()`` emits normalised output shape
  13. ``icu_message_audit.run_stage()`` emits normalised output shape
  14. No ``current_value`` field in en_locale_qc run_stage output
  15. No ``current_value`` field in icu_message_audit run_stage output
  16. en_locale_qc run_stage output still contains ``issue_type`` (AuditIssue compat)
  17. icu_message_audit run_stage output still contains ``issue_type`` (AuditIssue compat)
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from l10n_audit.core.audit_output_adapter import normalize_audit_finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_row(**overrides) -> dict:
    """Build a minimal finding as emitted by en_locale_qc's make_finding()."""
    row = {
        "key": "auth.login",
        "issue_type": "grammar",
        "severity": "medium",
        "message": "Incorrect grammar.",
        "old": "You can not login",
        "new": "You cannot login",
        "related": "",
    }
    row.update(overrides)
    return row


def _make_icu_raw_row(**overrides) -> dict:
    """Build a minimal finding as emitted by icu_message_audit's make_finding()."""
    row = {
        "key": "trips.count",
        "issue_type": "icu_branch_mismatch",
        "severity": "medium",
        "message": "ICU branch mismatch.",
        "old": "one",
        "new": "other",
        "related": "plural node 0",
        "audit_source": "icu_message_audit",
        "fix_mode": "review_required",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# 1. normalize_audit_finding: old → detected_value
# ---------------------------------------------------------------------------

class TestFieldMapping:

    def test_old_maps_to_detected_value(self):
        row = _make_raw_row(old="You can not login")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["detected_value"] == "You can not login"

    def test_new_maps_to_candidate_value(self):
        row = _make_raw_row(new="You cannot login")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["candidate_value"] == "You cannot login"

    def test_old_not_present_at_top_level_after_normalisation(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        # "old" must not survive as a top-level key
        assert "old" not in result

    def test_new_not_present_at_top_level_after_normalisation(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "new" not in result

    def test_candidate_value_empty_string_when_no_new(self):
        row = _make_raw_row()
        del row["new"]
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["candidate_value"] == ""

    def test_candidate_value_empty_string_when_new_is_none(self):
        row = _make_raw_row(new=None)
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["candidate_value"] == ""


# ---------------------------------------------------------------------------
# 2. audit_source + locale injection
# ---------------------------------------------------------------------------

class TestInjection:

    def test_audit_source_injected_when_absent(self):
        row = _make_raw_row()
        # no audit_source in row
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["audit_source"] == "en_locale_qc"

    def test_locale_injected_when_absent(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["locale"] == "en"

    def test_row_audit_source_is_preferred_when_present(self):
        row = _make_raw_row(audit_source="icu_message_audit")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        # row's own audit_source wins
        assert result["audit_source"] == "icu_message_audit"

    def test_locale_injected_for_cross_locale_audit(self):
        row = _make_icu_raw_row()
        result = normalize_audit_finding(row, audit_source="icu_message_audit", locale="en/ar")
        assert result["locale"] == "en/ar"


# ---------------------------------------------------------------------------
# 3. Unknown extra fields → _raw_metadata
# ---------------------------------------------------------------------------

class TestRawMetadata:

    def test_unknown_field_goes_to_raw_metadata(self):
        row = _make_raw_row(my_custom_field="some_value")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "_raw_metadata" in result
        assert result["_raw_metadata"]["my_custom_field"] == "some_value"

    def test_remapped_inputs_preserved_in_raw_metadata_when_no_unknown_fields(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "_raw_metadata" in result
        assert "old" in result["_raw_metadata"]
        assert "new" in result["_raw_metadata"]
        # Make sure no other unexpected fields are in raw metadata
        assert len(result["_raw_metadata"]) == 2

    def test_multiple_unknown_fields_all_preserved(self):
        row = _make_raw_row(rule_id="GRAMMAR_001", offset=12, error_length=6)
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["_raw_metadata"]["rule_id"] == "GRAMMAR_001"
        assert result["_raw_metadata"]["offset"] == 12
        assert result["_raw_metadata"]["error_length"] == 6


# ---------------------------------------------------------------------------
# 4. current_value must never appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsence:

    def test_current_value_not_in_result(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "current_value" not in result

    def test_current_value_not_injected_even_if_row_has_old(self):
        row = _make_raw_row(old="some value")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "current_value" not in result

    def test_row_containing_current_value_passed_to_raw_metadata_not_top_level(self):
        # A row that somehow already has current_value (e.g. from a previous stage)
        # must not have it promoted to top-level by the adapter.
        row = {**_make_raw_row(), "current_value": "hydrated_value"}
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert "current_value" not in result
        # It must land in _raw_metadata or be dropped — not promoted
        # (current_value is in _DOWNSTREAM_KNOWN so it passes through — but only if
        # it's not in _CORE_FIELDS. Let's verify it doesn't appear at top level.)
        assert result.get("current_value") is None


# ---------------------------------------------------------------------------
# 5. Defaults
# ---------------------------------------------------------------------------

class TestDefaults:

    def test_severity_defaults_to_medium_when_absent(self):
        row = _make_raw_row()
        del row["severity"]
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["severity"] == "medium"

    def test_fix_mode_defaults_to_review_required(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["fix_mode"] == "review_required"

    def test_related_defaults_to_empty_string(self):
        row = _make_raw_row()
        del row["related"]
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["related"] == ""


# ---------------------------------------------------------------------------
# 6. Guaranteed fields always present
# ---------------------------------------------------------------------------

class TestGuaranteedFields:

    def test_all_core_fields_present(self):
        row = _make_raw_row()
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        for field in ("key", "issue_type", "severity", "message",
                      "audit_source", "locale", "detected_value", "candidate_value",
                      "fix_mode", "related"):
            assert field in result, f"Missing guaranteed field: {field}"

    def test_key_passes_through(self):
        row = _make_raw_row(key="payments.failed")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["key"] == "payments.failed"

    def test_issue_type_passes_through(self):
        row = _make_raw_row(issue_type="whitespace")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["issue_type"] == "whitespace"

    def test_message_passes_through(self):
        row = _make_raw_row(message="Custom message.")
        result = normalize_audit_finding(row, audit_source="en_locale_qc", locale="en")
        assert result["message"] == "Custom message."


# ---------------------------------------------------------------------------
# 7. en_locale_qc.run_stage() output shape tests
# ---------------------------------------------------------------------------

def _make_minimal_runtime(tmp_path: Path):
    """Build the smallest runtime-like object that en_locale_qc.run_stage() needs."""
    en_json = tmp_path / "en.json"
    ar_json = tmp_path / "ar.json"
    en_json.write_text(json.dumps({"auth.login": "You can not login"}), encoding="utf-8")
    ar_json.write_text(json.dumps({"auth.login": "لا يمكنك تسجيل الدخول"}), encoding="utf-8")

    runtime = SimpleNamespace(
        en_file=en_json,
        ar_file=ar_json,
        source_locale="en",
        target_locales=["ar"],
        project_profile="generic",
        locale_format="json",

        results_dir=tmp_path / "results",
        config_dir=tmp_path / "config",
        code_dirs=[],
        usage_patterns=[],
        allowed_extensions=[".js", ".py"],
        role_identifiers=frozenset(),
        entity_whitelist={},
        metadata={},
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "config").mkdir()
    return runtime


def _make_minimal_options(write_reports: bool = False):
    options = MagicMock()
    options.write_reports = write_reports
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = {}
    options.audit_rules.latin_whitelist = []
    return options


class TestEnLocaleQcRunStageShape:

    def test_run_stage_returns_audit_issue_objects(self, tmp_path):
        from l10n_audit.models import AuditIssue
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert isinstance(item, AuditIssue)

    def test_run_stage_extra_contains_detected_value(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        # If any finding is produced, detected_value must be in .extra
        for item in results:
            assert "detected_value" in item.extra, (
                f"AuditIssue.extra missing 'detected_value' for key={item.key!r}"
            )

    def test_run_stage_extra_contains_candidate_value(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "candidate_value" in item.extra, (
                f"AuditIssue.extra missing 'candidate_value' for key={item.key!r}"
            )

    def test_run_stage_no_current_value_in_extra(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in extra (key={item.key!r})"
            )

    def test_run_stage_audit_source_in_extra(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert item.extra.get("audit_source") == "en_locale_qc", (
                f"Expected audit_source='en_locale_qc' in extra for key={item.key!r}"
            )

    def test_run_stage_locale_in_extra(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            # locale is a first-class AuditIssue field (not in extra)
            assert item.locale == "en", (
                f"Expected AuditIssue.locale='en' for key={item.key!r}, got {item.locale!r}"
            )

    def test_run_stage_issue_type_still_set(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        runtime = _make_minimal_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert item.issue_type, f"issue_type must be non-empty for key={item.key!r}"


# ---------------------------------------------------------------------------
# 8. icu_message_audit.run_stage() output shape tests
# ---------------------------------------------------------------------------

def _make_icu_runtime(tmp_path: Path):
    """Runtime with a key that triggers an ICU branch mismatch."""
    en_json = tmp_path / "en.json"
    ar_json = tmp_path / "ar.json"
    en_json.write_text(
        json.dumps({"trips.count": "{count, plural, one{1 trip} other{{count} trips}}"}),
        encoding="utf-8",
    )
    # AR uses a different branch set (no 'one') → icu_branch_mismatch
    ar_json.write_text(
        json.dumps({"trips.count": "{count, plural, few{رحلات} other{{count} رحلة}}"}),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(
        en_file=en_json,
        ar_file=ar_json,
        source_locale="en",
        target_locales=["ar"],
        project_profile="generic",
        locale_format="json",

        results_dir=tmp_path / "results",
        config_dir=tmp_path / "config",
        code_dirs=[],
        usage_patterns=[],
        allowed_extensions=[".js", ".py"],
        role_identifiers=frozenset(),
        entity_whitelist={},
        metadata={},
    )
    (tmp_path / "results").mkdir()
    (tmp_path / "config").mkdir()
    return runtime


class TestIcuMessageAuditRunStageShape:

    def test_run_stage_returns_audit_issue_objects(self, tmp_path):
        from l10n_audit.models import AuditIssue
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert isinstance(item, AuditIssue)

    def test_run_stage_extra_contains_detected_value(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "detected_value" in item.extra, (
                f"AuditIssue.extra missing 'detected_value' for key={item.key!r}"
            )

    def test_run_stage_extra_contains_candidate_value(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "candidate_value" in item.extra, (
                f"AuditIssue.extra missing 'candidate_value' for key={item.key!r}"
            )

    def test_run_stage_no_current_value_in_extra(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in ICU audit extra (key={item.key!r})"
            )

    def test_run_stage_audit_source_in_extra(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert item.extra.get("audit_source") == "icu_message_audit"

    def test_run_stage_locale_en_ar_in_extra(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            # locale is a first-class AuditIssue field (not in extra)
            assert item.locale == "en/ar", (
                f"Expected AuditIssue.locale='en/ar' for key={item.key!r}, got {item.locale!r}"
            )

    def test_run_stage_issue_type_still_set(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        runtime = _make_icu_runtime(tmp_path)
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert item.issue_type


# ---------------------------------------------------------------------------
# 9. Other audit modules NOT affected
# ---------------------------------------------------------------------------

class TestUntouchedModules:

    def test_ar_locale_qc_not_imported_by_adapter(self):
        """adapter module must not import ar_locale_qc or any other audit."""
        import importlib
        import re
        adapter = importlib.import_module("l10n_audit.core.audit_output_adapter")
        adapter_source = Path(adapter.__file__).read_text(encoding="utf-8")
        for forbidden in ("ar_locale_qc", "ar_semantic_qc", "terminology_audit",
                          "placeholder_audit", "ai_review", "en_grammar_audit"):
            # Ensure it's not imported via 'import' or 'from'
            match = re.search(rf"^(?:from|import)\s+.*{forbidden}", adapter_source, re.MULTILINE)
            assert match is None, (
                f"adapter_output_adapter.py must not import {forbidden!r}"
            )
