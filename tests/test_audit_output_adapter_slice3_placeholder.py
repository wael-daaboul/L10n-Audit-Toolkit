"""
tests/test_audit_output_adapter_slice3_placeholder.py
======================================================

Phase 7C Slice 3 Part 2 — focused tests for placeholder_audit adapter wiring.

Covers:
  1.  placeholder_audit.run_stage() returns AuditIssue objects
  2.  suggestion → candidate_value mapping
  3.  absence of "old" is handled safely (detected_value == "")
  4.  detected_value exists in extra (may be empty string)
  5.  candidate_value exists in extra (from suggestion)
  6.  en_placeholders / ar_placeholders preserved in _raw_metadata
  7.  no current_value field emitted
  8.  locale == "en/ar" in AuditIssue.locale
  9.  audit_source == "placeholder_audit" in extra
  10. issue_type non-empty
  11. issue_from_dict still produces valid AuditIssue
  12. adapter suggestion fallback does not break Slice 1/2/3-a previously normalised modules
  13. normalize_audit_finding unit-level: suggestion → candidate_value
  14. suggestion field not present at top-level after normalization
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from l10n_audit.core.audit_output_adapter import normalize_audit_finding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_placeholder_runtime(tmp_path: Path):
    """Minimal runtime that guarantees at least one placeholder finding.

    Key 'msg' has {name} in EN but missing in AR → 'missing_in_ar' finding.
    """
    en_json = tmp_path / "en.json"
    ar_json = tmp_path / "ar.json"
    en_json.write_text(
        json.dumps({"msg": "Hello {name}, welcome!", "plain": "No placeholders here."}),
        encoding="utf-8",
    )
    ar_json.write_text(
        json.dumps({"msg": "مرحبا، أهلاً!", "plain": "لا توجد عناصر نائبة."}),
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


def _make_minimal_options(write_reports: bool = False):
    options = MagicMock()
    options.write_reports = write_reports
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    return options


@pytest.fixture()
def placeholder_results(tmp_path):
    from l10n_audit.audits.placeholder_audit import run_stage
    runtime = _make_placeholder_runtime(tmp_path)
    options = _make_minimal_options()
    return run_stage(runtime, options)


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

class TestPlaceholderReturnType:

    def test_returns_list(self, placeholder_results):
        assert isinstance(placeholder_results, list)

    def test_items_are_audit_issue(self, placeholder_results):
        from l10n_audit.models import AuditIssue
        for item in placeholder_results:
            assert isinstance(item, AuditIssue), (
                f"Expected AuditIssue, got {type(item)!r}"
            )

    def test_at_least_one_finding_produced(self, placeholder_results):
        """The {name}-mismatch fixture guarantees at least one finding."""
        assert placeholder_results, (
            "Expected at least one placeholder finding — fixture may be wrong"
        )


# ---------------------------------------------------------------------------
# 2. suggestion → candidate_value mapping
# ---------------------------------------------------------------------------

class TestSuggestionToCandidateValue:

    def test_candidate_value_in_extra(self, placeholder_results):
        for item in placeholder_results:
            assert "candidate_value" in item.extra, (
                f"'candidate_value' missing from extra for key={item.key!r}"
            )

    def test_candidate_value_is_string(self, placeholder_results):
        for item in placeholder_results:
            assert isinstance(item.extra["candidate_value"], str), (
                f"candidate_value must be str for key={item.key!r}"
            )

    def test_candidate_value_populated_from_suggestion(self, placeholder_results):
        """At least one finding must have a non-empty candidate_value."""
        assert any(item.extra.get("candidate_value") for item in placeholder_results), (
            "Expected at least one finding with non-empty candidate_value from suggestion"
        )

    def test_suggestion_not_at_top_level_in_extra(self, placeholder_results):
        """'suggestion' must be consumed/remapped, not leaked as a top-level extra key."""
        for item in placeholder_results:
            assert "suggestion" not in item.extra, (
                f"'suggestion' must be remapped to 'candidate_value', "
                f"not remain in extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 3. detected_value — safe even with no "old" field
# ---------------------------------------------------------------------------

class TestDetectedValuePlaceholder:

    def test_detected_value_in_extra(self, placeholder_results):
        for item in placeholder_results:
            assert "detected_value" in item.extra, (
                f"'detected_value' missing from extra for key={item.key!r}"
            )

    def test_detected_value_is_string(self, placeholder_results):
        for item in placeholder_results:
            assert isinstance(item.extra["detected_value"], str), (
                f"detected_value must be str for key={item.key!r}"
            )

    def test_detected_value_is_empty_string_when_no_old(self, placeholder_results):
        """placeholder_audit findings have no 'old' field → detected_value must be ''."""
        for item in placeholder_results:
            assert item.extra["detected_value"] == "", (
                f"detected_value should be '' (no 'old' in placeholder findings) "
                f"for key={item.key!r}, got {item.extra['detected_value']!r}"
            )


# ---------------------------------------------------------------------------
# 4. Placeholder metadata preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestPlaceholderMetadataPreservation:

    def test_raw_metadata_present(self, placeholder_results):
        """en_placeholders / ar_placeholders are unknown to adapter → _raw_metadata."""
        for item in placeholder_results:
            assert "_raw_metadata" in item.extra, (
                f"_raw_metadata missing for key={item.key!r}; "
                f"en_placeholders/ar_placeholders must be preserved there"
            )

    def test_en_placeholders_in_raw_metadata(self, placeholder_results):
        for item in placeholder_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "en_placeholders" in meta, (
                f"'en_placeholders' missing from _raw_metadata for key={item.key!r}"
            )

    def test_ar_placeholders_in_raw_metadata(self, placeholder_results):
        for item in placeholder_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "ar_placeholders" in meta, (
                f"'ar_placeholders' missing from _raw_metadata for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 5. current_value must NOT appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsencePlaceholder:

    def test_no_current_value_in_extra(self, placeholder_results):
        for item in placeholder_results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in placeholder extra for key={item.key!r}"
            )

    def test_no_current_value_in_raw_metadata(self, placeholder_results):
        for item in placeholder_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "current_value" not in meta


# ---------------------------------------------------------------------------
# 6. locale and audit_source
# ---------------------------------------------------------------------------

class TestLocaleAndSourcePlaceholder:

    def test_locale_is_en_ar(self, placeholder_results):
        """Placeholder audit is cross-locale → locale should be 'en/ar'."""
        for item in placeholder_results:
            assert item.locale == "en/ar", (
                f"Expected AuditIssue.locale='en/ar' for key={item.key!r}, "
                f"got {item.locale!r}"
            )

    def test_audit_source_equals_placeholder_audit(self, placeholder_results):
        for item in placeholder_results:
            assert item.extra.get("audit_source") == "placeholder_audit", (
                f"Expected audit_source='placeholder_audit' for key={item.key!r}, "
                f"got {item.extra.get('audit_source')!r}"
            )


# ---------------------------------------------------------------------------
# 7. issue_type non-empty
# ---------------------------------------------------------------------------

class TestIssueTypePlaceholder:

    def test_issue_type_non_empty(self, placeholder_results):
        for item in placeholder_results:
            assert item.issue_type, f"issue_type must be non-empty for key={item.key!r}"


# ---------------------------------------------------------------------------
# 8. normalize_audit_finding unit-level: suggestion → candidate_value
# ---------------------------------------------------------------------------

class TestNormalizePlaceholderRow:
    """Direct unit tests on a placeholder-shaped raw row."""

    def _ph_row(self, **overrides) -> dict:
        row = {
            "key": "msg",
            "issue_type": "placeholder_mismatch",
            "severity": "high",
            "message": "Arabic is missing placeholders present in English: {name}",
            "en_placeholders": "{name}",
            "ar_placeholders": "(none)",
            "suggestion": "Copy the missing placeholder tokens into ar.json without renaming them.",
            "source": "placeholders",
        }
        row.update(overrides)
        return row

    def test_suggestion_maps_to_candidate_value(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["candidate_value"] == "Copy the missing placeholder tokens into ar.json without renaming them."

    def test_new_takes_priority_over_suggestion(self):
        """If both 'new' and 'suggestion' exist, 'new' wins."""
        row = self._ph_row(new="OVERRIDE_VALUE")
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["candidate_value"] == "OVERRIDE_VALUE"

    def test_no_old_yields_empty_detected_value(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["detected_value"] == ""

    def test_suggestion_not_at_top_level(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert "suggestion" not in result

    def test_en_placeholders_in_raw_metadata(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["_raw_metadata"]["en_placeholders"] == "{name}"

    def test_ar_placeholders_in_raw_metadata(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["_raw_metadata"]["ar_placeholders"] == "(none)"

    def test_no_current_value(self):
        row = self._ph_row()
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert "current_value" not in result

    def test_issue_from_dict_works(self):
        from l10n_audit.models import AuditIssue, issue_from_dict
        row = self._ph_row()
        normalized = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        issue = issue_from_dict(normalized)
        assert isinstance(issue, AuditIssue)
        assert issue.locale == "en/ar"
        assert issue.issue_type == "placeholder_mismatch"

    def test_empty_suggestion_yields_empty_candidate_value(self):
        row = self._ph_row(suggestion="")
        result = normalize_audit_finding(row, audit_source="placeholder_audit", locale="en/ar")
        assert result["candidate_value"] == ""


# ---------------------------------------------------------------------------
# 9. Regression: previously wired modules still work after adapter change
# ---------------------------------------------------------------------------

class TestPreviousSlicesUnaffectedByAdapterChange:

    def test_en_locale_qc_candidate_value_still_from_new(self, tmp_path):
        """Slices 1-3a used 'new' for candidate_value — must still work after suggestion added."""
        from l10n_audit.audits.en_locale_qc import run_stage
        en_json = tmp_path / "en.json"
        ar_json = tmp_path / "ar.json"
        en_json.write_text(json.dumps({"k": "You can not login"}), encoding="utf-8")
        ar_json.write_text(json.dumps({"k": "لا يمكنك"}), encoding="utf-8")
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=ar_json, source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            code_dirs=[], usage_patterns=[], allowed_extensions=[".js"],
            role_identifiers=frozenset(), entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(); (tmp_path / "config").mkdir()
        results = run_stage(runtime, _make_minimal_options())
        for item in results:
            assert "candidate_value" in item.extra
            assert "current_value" not in item.extra

    def test_suggestion_fallback_does_not_clobber_new(self):
        """When 'new' is present, 'suggestion' must not override it."""
        row = {
            "key": "k",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "test",
            "old": "old value",
            "new": "the fix",
            "suggestion": "descriptive text",
        }
        result = normalize_audit_finding(row, audit_source="test", locale="en")
        assert result["candidate_value"] == "the fix"
        assert result["detected_value"] == "old value"
