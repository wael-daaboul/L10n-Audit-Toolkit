"""
tests/test_audit_output_adapter_slice3.py
==========================================

Phase 7C Slice 3 — focused tests for ar_locale_qc adapter wiring.

Covers:
  1.  ar_locale_qc.run_stage() returns AuditIssue objects
  2.  detected_value present in extra (mapped from "old")
  3.  candidate_value present in extra (mapped from "new" / empty string fallback)
  4.  locale == "ar" in AuditIssue.locale
  5.  audit_source == "ar_locale_qc" in extra
  6.  no current_value field emitted
  7.  extra ar_locale_qc annotation fields preserved (context_type, ui_surface, etc.)
  8.  backward compat: issue_from_dict still produces valid AuditIssue
  9.  issue_type is non-empty
  10. Slice 1+2 modules unaffected (regression guard)
  11. normalize_audit_finding unit-level on ar_locale_qc-shaped row
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

def _make_ar_runtime(tmp_path: Path, ar_content: dict | None = None, en_content: dict | None = None):
    """Minimal runtime for ar_locale_qc.run_stage()."""
    if ar_content is None:
        # Use a value that triggers a detectable Arabic QC issue.
        # Mixed RTL/LTR numbers with no real violation needed — just a plain
        # Arabic string is enough since ar_locale_qc checks spacing, empty,
        # missing keys etc.  Use a key present in EN but with an empty AR value
        # to guarantee at least one finding.
        ar_content = {
            "greeting": "مرحبا",   # non-empty: may or may not trigger a rule
            "empty_key": "",        # empty AR value → guaranteed finding
        }
    if en_content is None:
        en_content = {
            "greeting": "Hello",
            "empty_key": "Empty placeholder",
        }

    ar_json = tmp_path / "ar.json"
    en_json = tmp_path / "en.json"
    ar_json.write_text(json.dumps(ar_content), encoding="utf-8")
    en_json.write_text(json.dumps(en_content), encoding="utf-8")

    glossary_json = tmp_path / "config" / "glossary.json"
    config_json = tmp_path / "config" / "config.json"
    (tmp_path / "config").mkdir(exist_ok=True)
    glossary_json.write_text(json.dumps({"terms": [], "rules": {}}), encoding="utf-8")
    config_json.write_text(json.dumps({}), encoding="utf-8")

    runtime = SimpleNamespace(
        en_file=en_json,
        ar_file=ar_json,
        source_locale="en",
        target_locales=["ar"],
        project_profile="generic",
        locale_format="json",
        results_dir=tmp_path / "results",
        config_dir=tmp_path / "config",
        glossary_file=glossary_json,
        code_dirs=[],
        usage_patterns=[],
        allowed_extensions=[".js", ".py"],
        role_identifiers=frozenset(),
        entity_whitelist={},
        metadata={},
    )
    (tmp_path / "results").mkdir(exist_ok=True)
    return runtime


def _make_minimal_options(write_reports: bool = False):
    options = MagicMock()
    options.write_reports = write_reports
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    options.audit_rules = MagicMock()
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = {}
    options.audit_rules.latin_whitelist = []
    options.ai_review = MagicMock()
    options.ai_review.enabled = False
    return options


@pytest.fixture()
def ar_qc_results(tmp_path):
    from l10n_audit.audits.ar_locale_qc import run_stage
    runtime = _make_ar_runtime(tmp_path)
    options = _make_minimal_options()
    return run_stage(runtime, options)


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

class TestArLocaleQcReturnType:

    def test_run_stage_returns_list(self, ar_qc_results):
        assert isinstance(ar_qc_results, list)

    def test_run_stage_items_are_audit_issue(self, ar_qc_results):
        from l10n_audit.models import AuditIssue
        for item in ar_qc_results:
            assert isinstance(item, AuditIssue), (
                f"Expected AuditIssue, got {type(item)!r} for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 2. detected_value (old → detected_value)
# ---------------------------------------------------------------------------

class TestDetectedValueAr:

    def test_detected_value_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "detected_value" in item.extra, (
                f"'detected_value' missing from extra for key={item.key!r}"
            )

    def test_detected_value_is_string(self, ar_qc_results):
        for item in ar_qc_results:
            assert isinstance(item.extra["detected_value"], str), (
                f"detected_value must be str for key={item.key!r}"
            )

    def test_old_not_at_top_level_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "old" not in item.extra, (
                f"'old' must be remapped to 'detected_value', not remain in extra "
                f"for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 3. candidate_value (new → candidate_value, always present)
# ---------------------------------------------------------------------------

class TestCandidateValueAr:

    def test_candidate_value_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "candidate_value" in item.extra, (
                f"'candidate_value' missing from extra for key={item.key!r}"
            )

    def test_candidate_value_is_string(self, ar_qc_results):
        for item in ar_qc_results:
            assert isinstance(item.extra["candidate_value"], str), (
                f"candidate_value must be str for key={item.key!r}"
            )

    def test_new_not_at_top_level_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "new" not in item.extra, (
                f"'new' must be remapped to 'candidate_value', not remain in extra "
                f"for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 4. locale == "ar"
# ---------------------------------------------------------------------------

class TestLocaleAr:

    def test_locale_is_ar(self, ar_qc_results):
        for item in ar_qc_results:
            # locale is a first-class AuditIssue field
            assert item.locale == "ar", (
                f"Expected AuditIssue.locale='ar' for key={item.key!r}, "
                f"got {item.locale!r}"
            )


# ---------------------------------------------------------------------------
# 5. audit_source injection
# ---------------------------------------------------------------------------

class TestAuditSourceAr:

    def test_audit_source_equals_ar_locale_qc(self, ar_qc_results):
        for item in ar_qc_results:
            assert item.extra.get("audit_source") == "ar_locale_qc", (
                f"Expected audit_source='ar_locale_qc' for key={item.key!r}, "
                f"got {item.extra.get('audit_source')!r}"
            )


# ---------------------------------------------------------------------------
# 6. current_value must NOT appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsenceAr:

    def test_no_current_value_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in ar_locale_qc extra "
                f"for key={item.key!r}"
            )

    def test_no_current_value_in_raw_metadata(self, ar_qc_results):
        for item in ar_qc_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "current_value" not in meta, (
                f"'current_value' must not appear in _raw_metadata "
                f"for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 7. ar_locale_qc annotation fields preserved
# ---------------------------------------------------------------------------

class TestAnnotationFieldsAr:
    """context_type, ui_surface, etc. are in _PRESERVE_TOP_LEVEL → must survive."""

    def test_fix_mode_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "fix_mode" in item.extra, (
                f"'fix_mode' missing from extra for key={item.key!r}"
            )

    def test_context_type_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "context_type" in item.extra, (
                f"'context_type' missing from extra for key={item.key!r}"
            )

    def test_ui_surface_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "ui_surface" in item.extra, (
                f"'ui_surface' missing from extra for key={item.key!r}"
            )

    def test_semantic_risk_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "semantic_risk" in item.extra, (
                f"'semantic_risk' missing from extra for key={item.key!r}"
            )

    def test_review_reason_in_extra(self, ar_qc_results):
        for item in ar_qc_results:
            assert "review_reason" in item.extra, (
                f"'review_reason' missing from extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 8. issue_type non-empty
# ---------------------------------------------------------------------------

class TestIssueTypeAr:

    def test_issue_type_non_empty(self, ar_qc_results):
        for item in ar_qc_results:
            assert item.issue_type, (
                f"issue_type must be non-empty for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 9. normalize_audit_finding unit-level on ar_locale_qc-shaped raw row
# ---------------------------------------------------------------------------

class TestNormalizeArRow:
    """Direct unit tests for the adapter on an ar_locale_qc-shaped raw row."""

    def _ar_raw_row(self, **overrides) -> dict:
        row = {
            "key": "greeting",
            "issue_type": "empty_ar",
            "severity": "medium",
            "message": "Arabic translation is empty.",
            "old": "",
            "new": "",
            "related": "",
            "audit_source": "ar_locale_qc",
            "fix_mode": "review_required",
            "context_type": "ui_label",
            "ui_surface": "button",
            "text_role": "label",
            "action_hint": "",
            "audience_hint": "",
            "context_flags": "",
            "semantic_risk": "low",
            "lt_signals": "{}",
            "review_reason": "",
            "source": "ar_locale_qc",
        }
        row.update(overrides)
        return row

    def test_old_maps_to_detected_value(self):
        row = self._ar_raw_row(old="مرحبا")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["detected_value"] == "مرحبا"

    def test_new_maps_to_candidate_value(self):
        row = self._ar_raw_row(new="أهلاً")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["candidate_value"] == "أهلاً"

    def test_candidate_value_empty_string_when_new_absent(self):
        row = self._ar_raw_row()
        del row["new"]
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["candidate_value"] == ""

    def test_locale_injected(self):
        row = self._ar_raw_row()
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["locale"] == "ar"

    def test_audit_source_preserved(self):
        row = self._ar_raw_row()
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["audit_source"] == "ar_locale_qc"

    def test_context_type_top_level(self):
        row = self._ar_raw_row(context_type="ui_label")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["context_type"] == "ui_label"

    def test_ui_surface_top_level(self):
        row = self._ar_raw_row(ui_surface="button")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["ui_surface"] == "button"

    def test_semantic_risk_top_level(self):
        row = self._ar_raw_row(semantic_risk="high")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert result["semantic_risk"] == "high"

    def test_no_current_value(self):
        row = self._ar_raw_row()
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert "current_value" not in result

    def test_old_not_at_top_level(self):
        row = self._ar_raw_row(old="مرحبا")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert "old" not in result

    def test_new_not_at_top_level(self):
        row = self._ar_raw_row(new="أهلاً")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert "new" not in result

    def test_extra_unknown_field_goes_to_raw_metadata(self):
        row = self._ar_raw_row(custom_field="value123")
        result = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        assert "_raw_metadata" in result
        assert result["_raw_metadata"]["custom_field"] == "value123"

    def test_issue_from_dict_still_works(self):
        from l10n_audit.models import AuditIssue, issue_from_dict
        row = self._ar_raw_row()
        normalized = normalize_audit_finding(row, audit_source="ar_locale_qc", locale="ar")
        issue = issue_from_dict(normalized)
        assert isinstance(issue, AuditIssue)
        assert issue.locale == "ar"
        assert issue.issue_type == "empty_ar"


# ---------------------------------------------------------------------------
# 10. Slice 1+2 regression guards
# ---------------------------------------------------------------------------

class TestPreviousSlicesUnaffected:

    def test_en_locale_qc_still_normalised(self, tmp_path):
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
            assert "detected_value" in item.extra
            assert "current_value" not in item.extra

    def test_en_grammar_audit_still_normalised(self, tmp_path):
        from l10n_audit.audits.en_grammar_audit import run_stage
        en_json = tmp_path / "en.json"
        en_json.write_text(json.dumps({"k": "You can not login"}), encoding="utf-8")
        (tmp_path / "ar.json").write_text("{}", encoding="utf-8")
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=tmp_path / "ar.json", source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            code_dirs=[], usage_patterns=[], allowed_extensions=[".js"],
            role_identifiers=frozenset(), entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(); (tmp_path / "config").mkdir()
        results = run_stage(runtime, _make_minimal_options())
        for item in results:
            assert "detected_value" in item.extra
            assert "current_value" not in item.extra
