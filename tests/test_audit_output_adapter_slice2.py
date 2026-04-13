"""
tests/test_audit_output_adapter_slice2.py
==========================================

Phase 7C Slice 2 — focused tests for en_grammar_audit adapter wiring.

Covers:
  1.  en_grammar_audit.run_stage() returns AuditIssue objects
  2.  detected_value present in extra (mapped from "old")
  3.  candidate_value present in extra (mapped from "new")
  4.  grammar metadata preserved in _raw_metadata (rule_id, context, offset, error_length)
  5.  no current_value field emitted
  6.  audit_source == "en_grammar_audit" in extra
  7.  locale == "en" in AuditIssue.locale
  8.  issue_type is non-empty
  9.  replacements preserved in _raw_metadata
  10. Slice 1 modules (en_locale_qc, icu_message_audit) remain unaffected by Slice 2
  11. Adapter module docstring updated to reference Slice 2 (sanity check)
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

def _make_grammar_runtime(tmp_path: Path, en_content: dict | None = None):
    """Minimal runtime for en_grammar_audit.run_stage()."""
    if en_content is None:
        # "can not" triggers the CUSTOM_RULES CUSTOM::can not rule reliably
        en_content = {"auth.login_error": "You can not login to your account."}

    en_json = tmp_path / "en.json"
    en_json.write_text(json.dumps(en_content), encoding="utf-8")

    runtime = SimpleNamespace(
        en_file=en_json,
        ar_file=tmp_path / "ar.json",   # grammar audit only reads EN
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
    # ar.json not needed by grammar audit, but creates it to avoid any path errors
    (tmp_path / "ar.json").write_text("{}", encoding="utf-8")
    return runtime


def _make_minimal_options(write_reports: bool = False):
    options = MagicMock()
    options.write_reports = write_reports
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    return options


# ---------------------------------------------------------------------------
# Helper: run grammar audit against the "can not" fixture and return results
# (all grammar-specific tests reuse this via a shared fixture)
# ---------------------------------------------------------------------------

@pytest.fixture()
def grammar_results(tmp_path):
    from l10n_audit.audits.en_grammar_audit import run_stage
    runtime = _make_grammar_runtime(tmp_path)
    options = _make_minimal_options()
    return run_stage(runtime, options)


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

class TestEnGrammarAuditReturnType:

    def test_run_stage_returns_list(self, grammar_results):
        assert isinstance(grammar_results, list)

    def test_run_stage_list_items_are_audit_issue(self, grammar_results):
        from l10n_audit.models import AuditIssue
        for item in grammar_results:
            assert isinstance(item, AuditIssue), (
                f"Expected AuditIssue, got {type(item)!r}"
            )


# ---------------------------------------------------------------------------
# 2. detected_value (old → detected_value)
# ---------------------------------------------------------------------------

class TestDetectedValue:

    def test_detected_value_in_extra(self, grammar_results):
        for item in grammar_results:
            assert "detected_value" in item.extra, (
                f"'detected_value' missing from extra for key={item.key!r}"
            )

    def test_detected_value_is_string(self, grammar_results):
        for item in grammar_results:
            assert isinstance(item.extra["detected_value"], str)

    def test_detected_value_not_empty_for_triggered_finding(self, grammar_results):
        # "can not" fixture must trigger at least one finding with a non-empty detected_value
        assert grammar_results, "Expected at least one grammar finding for 'can not' fixture"
        assert any(item.extra.get("detected_value") for item in grammar_results), (
            "At least one finding must have a non-empty detected_value"
        )

    def test_old_field_not_present_at_top_level_in_extra(self, grammar_results):
        for item in grammar_results:
            # "old" must have been remapped — it must not survive as a top-level extra key
            assert "old" not in item.extra, (
                f"'old' should be remapped to 'detected_value', not remain in extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 3. candidate_value (new → candidate_value)
# ---------------------------------------------------------------------------

class TestCandidateValue:

    def test_candidate_value_in_extra(self, grammar_results):
        for item in grammar_results:
            assert "candidate_value" in item.extra, (
                f"'candidate_value' missing from extra for key={item.key!r}"
            )

    def test_candidate_value_is_string(self, grammar_results):
        for item in grammar_results:
            assert isinstance(item.extra["candidate_value"], str)

    def test_new_field_not_present_at_top_level_in_extra(self, grammar_results):
        for item in grammar_results:
            assert "new" not in item.extra, (
                f"'new' should be remapped to 'candidate_value', not remain in extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 4. Grammar-specific metadata preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestGrammarMetadataPreservation:

    def test_raw_metadata_present_for_grammar_findings(self, grammar_results):
        """Grammar findings carry rule_id/context/offset → _raw_metadata must exist."""
        for item in grammar_results:
            assert "_raw_metadata" in item.extra, (
                f"Grammar finding missing '_raw_metadata' for key={item.key!r}. "
                f"Fields rule_id/context/offset/error_length must be preserved."
            )

    def test_rule_id_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "rule_id" in meta, (
                f"'rule_id' missing from _raw_metadata for key={item.key!r}"
            )

    def test_context_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "context" in meta, (
                f"'context' missing from _raw_metadata for key={item.key!r}"
            )

    def test_offset_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "offset" in meta, (
                f"'offset' missing from _raw_metadata for key={item.key!r}"
            )

    def test_error_length_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "error_length" in meta, (
                f"'error_length' missing from _raw_metadata for key={item.key!r}"
            )

    def test_replacements_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "replacements" in meta, (
                f"'replacements' missing from _raw_metadata for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 5. current_value must NOT appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsenceGrammar:

    def test_no_current_value_in_extra(self, grammar_results):
        for item in grammar_results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in grammar audit extra for key={item.key!r}"
            )

    def test_no_current_value_in_raw_metadata(self, grammar_results):
        for item in grammar_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "current_value" not in meta, (
                f"'current_value' must not appear in _raw_metadata for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 6. audit_source injection
# ---------------------------------------------------------------------------

class TestAuditSourceGrammar:

    def test_audit_source_equals_en_grammar_audit(self, grammar_results):
        for item in grammar_results:
            assert item.extra.get("audit_source") == "en_grammar_audit", (
                f"Expected audit_source='en_grammar_audit' for key={item.key!r}, "
                f"got {item.extra.get('audit_source')!r}"
            )


# ---------------------------------------------------------------------------
# 7. locale injection
# ---------------------------------------------------------------------------

class TestLocaleGrammar:

    def test_locale_is_en(self, grammar_results):
        for item in grammar_results:
            # locale is a first-class AuditIssue field (not in extra)
            assert item.locale == "en", (
                f"Expected AuditIssue.locale='en' for key={item.key!r}, got {item.locale!r}"
            )


# ---------------------------------------------------------------------------
# 8. issue_type non-empty
# ---------------------------------------------------------------------------

class TestIssueTypeGrammar:

    def test_issue_type_is_non_empty(self, grammar_results):
        for item in grammar_results:
            assert item.issue_type, (
                f"issue_type must be non-empty for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 9. normalize_audit_finding unit test for grammar-shaped row
# ---------------------------------------------------------------------------

class TestNormalizeGrammarRow:
    """Direct unit tests for the adapter on a grammar-shaped raw row."""

    def _grammar_row(self, **overrides) -> dict:
        row = {
            "key": "auth.login_error",
            "issue_type": "Style/grammar",
            "rule_id": "CUSTOM::can not",
            "message": "Matched custom rule: can not",
            "old": "You can not login to your account.",
            "new": "You cannot login to your account.",
            "replacements": "cannot",
            "context": "You can not login to your account.",
            "offset": "",
            "error_length": "",
            "source": "grammar",
        }
        row.update(overrides)
        return row

    def test_old_maps_to_detected_value(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert result["detected_value"] == "You can not login to your account."

    def test_new_maps_to_candidate_value(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert result["candidate_value"] == "You cannot login to your account."

    def test_rule_id_in_raw_metadata(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert result["_raw_metadata"]["rule_id"] == "CUSTOM::can not"

    def test_context_in_raw_metadata(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "context" in result["_raw_metadata"]

    def test_offset_in_raw_metadata(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "offset" in result["_raw_metadata"]

    def test_error_length_in_raw_metadata(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "error_length" in result["_raw_metadata"]

    def test_replacements_in_raw_metadata(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert result["_raw_metadata"]["replacements"] == "cannot"

    def test_decision_passes_through_top_level(self):
        """decision dict (from LanguageTool findings) must survive as top-level."""
        row = self._grammar_row(decision={"route": "auto_fix", "confidence": 0.9, "risk": "low", "engine_version": "v3"})
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "decision" in result
        assert result["decision"]["route"] == "auto_fix"

    def test_no_current_value_emitted(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "current_value" not in result

    def test_old_not_at_top_level(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "old" not in result

    def test_new_not_at_top_level(self):
        row = self._grammar_row()
        result = normalize_audit_finding(row, audit_source="en_grammar_audit", locale="en")
        assert "new" not in result


# ---------------------------------------------------------------------------
# 10. Slice 1 modules unaffected (regression guards)
# ---------------------------------------------------------------------------

class TestSlice1ModulesUnaffected:
    """Ensure Slice 2 did not alter en_locale_qc or icu_message_audit behaviour."""

    def test_en_locale_qc_still_emits_detected_value(self, tmp_path):
        from l10n_audit.audits.en_locale_qc import run_stage
        en_json = tmp_path / "en.json"
        ar_json = tmp_path / "ar.json"
        en_json.write_text(json.dumps({"auth.login": "You can not login"}), encoding="utf-8")
        ar_json.write_text(json.dumps({"auth.login": "لا يمكنك"}), encoding="utf-8")
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=ar_json, source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            code_dirs=[], usage_patterns=[], allowed_extensions=[".js"],
            role_identifiers=frozenset(), entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(); (tmp_path / "config").mkdir()
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "detected_value" in item.extra
            assert "current_value" not in item.extra

    def test_icu_message_audit_still_emits_detected_value(self, tmp_path):
        from l10n_audit.audits.icu_message_audit import run_stage
        en_json = tmp_path / "en.json"
        ar_json = tmp_path / "ar.json"
        en_json.write_text(
            json.dumps({"t.count": "{count, plural, one{1 trip} other{{count} trips}}"}),
            encoding="utf-8",
        )
        ar_json.write_text(
            json.dumps({"t.count": "{count, plural, few{رحلات} other{{count} رحلة}}"}),
            encoding="utf-8",
        )
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=ar_json, source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            code_dirs=[], usage_patterns=[], allowed_extensions=[".js"],
            role_identifiers=frozenset(), entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(); (tmp_path / "config").mkdir()
        options = _make_minimal_options()
        results = run_stage(runtime, options)
        for item in results:
            assert "detected_value" in item.extra
            assert "current_value" not in item.extra
