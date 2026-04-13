"""
tests/test_audit_output_adapter_slice3_semantic.py
===================================================

Phase 7C Slice 3 Part 3 — focused tests for ar_semantic_qc adapter wiring.

Covers:
  1.  ar_semantic_qc.run_stage() returns AuditIssue objects
  2.  old → detected_value
  3.  candidate_value remains candidate_value (not re-aliased)
  4.  suggestion_confidence preserved in _raw_metadata
  5.  fix_mode preserved top-level
  6.  no current_value emitted
  7.  issue_from_dict() still produces valid AuditIssue
  8.  audit_source == "ar_semantic_qc" in extra
  9.  locale == "ar" in AuditIssue.locale
  10. semantic annotation fields (context_type, semantic_risk, etc.) preserved
  11. enforcement_skipped preserved safely
  12. adapter does not interfere with routing metadata shape (decision dict)
  13. Slice 1/2/3a/3b previously wired modules remain unaffected
  14. normalize_audit_finding unit-level on ar_semantic_qc-shaped row
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

def _make_semantic_runtime(tmp_path: Path):
    """Minimal runtime for ar_semantic_qc.run_stage().

    Uses a long English sentence vs. a very short Arabic label to trigger
    a 'sentence_shape_mismatch' or 'possible_meaning_loss' finding reliably
    without depending on LanguageTool being available.
    """
    en_json = tmp_path / "en.json"
    ar_json = tmp_path / "ar.json"
    en_json.write_text(
        json.dumps({
            # Long sentence in EN, very short label in AR → triggers sentence_shape_mismatch
            "trips.save_action": "Please save your trip details before continuing to the next step.",
            # Simple pair that should produce no finding
            "trips.title": "My Trips",
        }),
        encoding="utf-8",
    )
    ar_json.write_text(
        json.dumps({
            "trips.save_action": "أحفظ",   # very short → shape mismatch vs long EN sentence
            "trips.title": "رحلاتي",
        }),
        encoding="utf-8",
    )

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


def _make_semantic_options():
    options = MagicMock()
    options.write_reports = False
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = {}
    options.ai_review.short_label_threshold = 3
    return options


@pytest.fixture()
def semantic_results(tmp_path):
    from l10n_audit.audits.ar_semantic_qc import run_stage
    runtime = _make_semantic_runtime(tmp_path)
    options = _make_semantic_options()
    return run_stage(runtime, options)


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

class TestArSemanticQcReturnType:

    def test_returns_list(self, semantic_results):
        assert isinstance(semantic_results, list)

    def test_items_are_audit_issue(self, semantic_results):
        from l10n_audit.models import AuditIssue
        for item in semantic_results:
            assert isinstance(item, AuditIssue), (
                f"Expected AuditIssue, got {type(item)!r} for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 2. detected_value (old → detected_value)
# ---------------------------------------------------------------------------

class TestDetectedValueSemantic:

    def test_detected_value_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "detected_value" in item.extra, (
                f"'detected_value' missing from extra for key={item.key!r}"
            )

    def test_detected_value_is_string(self, semantic_results):
        for item in semantic_results:
            assert isinstance(item.extra["detected_value"], str), (
                f"detected_value must be str for key={item.key!r}"
            )

    def test_old_not_at_top_level_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "old" not in item.extra, (
                f"'old' must be remapped to 'detected_value', not remain in extra "
                f"for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 3. candidate_value preserved correctly
# ---------------------------------------------------------------------------

class TestCandidateValueSemantic:

    def test_candidate_value_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "candidate_value" in item.extra, (
                f"'candidate_value' missing from extra for key={item.key!r}"
            )

    def test_candidate_value_is_string(self, semantic_results):
        for item in semantic_results:
            assert isinstance(item.extra["candidate_value"], str), (
                f"candidate_value must be str for key={item.key!r}"
            )

    def test_new_not_at_top_level_in_extra(self, semantic_results):
        """ar_semantic_qc never emits 'new' — confirm it does not appear after wiring."""
        for item in semantic_results:
            assert "new" not in item.extra, (
                f"'new' must not appear in extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 4. suggestion_confidence preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestSuggestionConfidenceSemantic:

    def test_suggestion_confidence_preserved(self, semantic_results):
        """suggestion_confidence is unknown to adapter → must land in _raw_metadata."""
        for item in semantic_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "suggestion_confidence" in meta, (
                f"'suggestion_confidence' missing from _raw_metadata for key={item.key!r}. "
                f"extra keys: {list(item.extra.keys())}"
            )

    def test_suggestion_confidence_is_string(self, semantic_results):
        for item in semantic_results:
            meta = item.extra.get("_raw_metadata", {})
            val = meta.get("suggestion_confidence", "")
            assert isinstance(val, str), (
                f"suggestion_confidence must be str for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 5. fix_mode preserved top-level
# ---------------------------------------------------------------------------

class TestFixModeSemantic:

    def test_fix_mode_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "fix_mode" in item.extra, (
                f"'fix_mode' missing from extra for key={item.key!r}"
            )

    def test_fix_mode_is_review_required(self, semantic_results):
        for item in semantic_results:
            assert item.extra["fix_mode"] == "review_required", (
                f"fix_mode must be 'review_required' for key={item.key!r}, "
                f"got {item.extra['fix_mode']!r}"
            )


# ---------------------------------------------------------------------------
# 6. current_value must NOT appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsenceSemantic:

    def test_no_current_value_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "current_value" not in item.extra, (
                f"'current_value' must not appear in semantic extra for key={item.key!r}"
            )

    def test_no_current_value_in_raw_metadata(self, semantic_results):
        for item in semantic_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "current_value" not in meta


# ---------------------------------------------------------------------------
# 7. audit_source and locale
# ---------------------------------------------------------------------------

class TestAuditSourceLocaleSemantic:

    def test_audit_source_equals_ar_semantic_qc(self, semantic_results):
        for item in semantic_results:
            assert item.extra.get("audit_source") == "ar_semantic_qc", (
                f"Expected audit_source='ar_semantic_qc' for key={item.key!r}, "
                f"got {item.extra.get('audit_source')!r}"
            )

    def test_locale_is_ar(self, semantic_results):
        for item in semantic_results:
            assert item.locale == "ar", (
                f"Expected AuditIssue.locale='ar' for key={item.key!r}, "
                f"got {item.locale!r}"
            )


# ---------------------------------------------------------------------------
# 8. Semantic annotation fields preserved top-level
# ---------------------------------------------------------------------------

class TestSemanticAnnotationFields:

    def test_context_type_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "context_type" in item.extra, (
                f"'context_type' missing from extra for key={item.key!r}"
            )

    def test_semantic_risk_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "semantic_risk" in item.extra, (
                f"'semantic_risk' missing from extra for key={item.key!r}"
            )

    def test_review_reason_in_extra(self, semantic_results):
        for item in semantic_results:
            assert "review_reason" in item.extra, (
                f"'review_reason' missing from extra for key={item.key!r}"
            )

    def test_enforcement_skipped_preserved(self, semantic_results):
        """enforcement_skipped is added by the enforcement loop — must survive."""
        for item in semantic_results:
            # enforcement_skipped is in _PRESERVE_TOP_LEVEL → must be in extra
            assert "enforcement_skipped" in item.extra, (
                f"'enforcement_skipped' missing from extra for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 9. issue_type non-empty
# ---------------------------------------------------------------------------

class TestIssueTypeSemantic:

    def test_issue_type_non_empty(self, semantic_results):
        for item in semantic_results:
            assert item.issue_type, f"issue_type must be non-empty for key={item.key!r}"


# ---------------------------------------------------------------------------
# 10. normalize_audit_finding unit-level: ar_semantic_qc-shaped row
# ---------------------------------------------------------------------------

class TestNormalizeSemanticRow:

    def _semantic_row(self, **overrides) -> dict:
        row = {
            "key": "trips.save_action",
            "issue_type": "sentence_shape_mismatch",
            "severity": "medium",
            "message": "English source is sentence-like, but the Arabic text appears too short.",
            "old": "أحفظ",
            "candidate_value": "أحفظ رحلتك",
            "fix_mode": "review_required",
            "suggestion_confidence": "medium",
            "audit_source": "ar_semantic_qc",
            "context_type": "ui_form",
            "ui_surface": "button",
            "text_role": "action",
            "action_hint": "save",
            "audience_hint": "",
            "context_flags": "",
            "semantic_risk": "low",
            "lt_signals": "{}",
            "review_reason": "",
            "enforcement_skipped": False,
            "source": "ar_semantic_qc",
        }
        row.update(overrides)
        return row

    def test_old_maps_to_detected_value(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert result["detected_value"] == "أحفظ"

    def test_candidate_value_preserved(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert result["candidate_value"] == "أحفظ رحلتك"

    def test_suggestion_confidence_in_raw_metadata(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert "_raw_metadata" in result
        assert result["_raw_metadata"]["suggestion_confidence"] == "medium"

    def test_fix_mode_top_level(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert result["fix_mode"] == "review_required"

    def test_enforcement_skipped_top_level(self):
        row = self._semantic_row(enforcement_skipped=True)
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert "enforcement_skipped" in result
        assert result["enforcement_skipped"] is True

    def test_no_current_value(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert "current_value" not in result

    def test_old_not_at_top_level(self):
        row = self._semantic_row()
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert "old" not in result

    def test_context_type_top_level(self):
        row = self._semantic_row(context_type="ui_form")
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert result["context_type"] == "ui_form"

    def test_semantic_risk_top_level(self):
        row = self._semantic_row(semantic_risk="high")
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert result["semantic_risk"] == "high"

    def test_issue_from_dict_works(self):
        from l10n_audit.models import AuditIssue, issue_from_dict
        row = self._semantic_row()
        normalized = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        issue = issue_from_dict(normalized)
        assert isinstance(issue, AuditIssue)
        assert issue.locale == "ar"
        assert issue.issue_type == "sentence_shape_mismatch"

    def test_empty_candidate_value_stays_empty(self):
        """candidate_value="" (disabled fix) must not be clobbered by suggestion fallback."""
        row = self._semantic_row(candidate_value="")
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        # note: "new" is absent, "candidate_value"="" is falsy → suggestion fallback kicks in
        # only if suggestion field is also absent. Since semantic rows have no "suggestion"
        # field, candidate_value must remain "".
        assert result["candidate_value"] == ""

    def test_decision_dict_passes_through_if_present(self):
        """decision dict from apply_arabic_decision_routing survives in extra."""
        row = self._semantic_row(decision={"route": "manual_review", "confidence": 0.4, "risk": "medium", "engine_version": "v3"})
        result = normalize_audit_finding(row, audit_source="ar_semantic_qc", locale="ar")
        assert "decision" in result
        assert result["decision"]["route"] == "manual_review"


# ---------------------------------------------------------------------------
# 11. Regression guards — previous slices unaffected
# ---------------------------------------------------------------------------

class TestPreviousSlicesUnaffectedBySemantic:

    def test_placeholder_audit_still_normalised(self, tmp_path):
        from l10n_audit.audits.placeholder_audit import run_stage
        en_json = tmp_path / "en.json"
        ar_json = tmp_path / "ar.json"
        en_json.write_text(json.dumps({"k": "Hello {name}!"}), encoding="utf-8")
        ar_json.write_text(json.dumps({"k": "مرحبا!"}), encoding="utf-8")
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=ar_json, source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            code_dirs=[], usage_patterns=[], allowed_extensions=[".js"],
            role_identifiers=frozenset(), entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(); (tmp_path / "config").mkdir()
        options = MagicMock()
        options.write_reports = False
        options.suppression.include_per_tool_csv = False
        options.suppression.include_per_tool_xlsx = False
        options.effective_output_dir = lambda base: base
        results = run_stage(runtime, options)
        for item in results:
            assert "candidate_value" in item.extra
            assert "current_value" not in item.extra

    def test_ar_locale_qc_still_normalised(self, tmp_path):
        from l10n_audit.audits.ar_locale_qc import run_stage
        en_json = tmp_path / "en.json"
        ar_json = tmp_path / "ar.json"
        en_json.write_text(json.dumps({"k": "Hello", "e": "Empty"}), encoding="utf-8")
        ar_json.write_text(json.dumps({"k": "مرحبا", "e": ""}), encoding="utf-8")
        glossary_json = tmp_path / "config" / "glossary.json"
        (tmp_path / "config").mkdir(exist_ok=True)
        glossary_json.write_text(json.dumps({"terms": [], "rules": {}}), encoding="utf-8")
        runtime = SimpleNamespace(
            en_file=en_json, ar_file=ar_json, source_locale="en",
            target_locales=["ar"], project_profile="generic", locale_format="json",
            results_dir=tmp_path / "results", config_dir=tmp_path / "config",
            glossary_file=glossary_json, code_dirs=[], usage_patterns=[],
            allowed_extensions=[".js"], role_identifiers=frozenset(),
            entity_whitelist={}, metadata={},
        )
        (tmp_path / "results").mkdir(exist_ok=True)
        options = MagicMock()
        options.write_reports = False
        options.suppression.include_per_tool_csv = False
        options.suppression.include_per_tool_xlsx = False
        options.effective_output_dir = lambda base: base
        options.audit_rules = MagicMock()
        options.audit_rules.role_identifiers = []
        options.audit_rules.entity_whitelist = {}
        options.audit_rules.latin_whitelist = []
        options.ai_review.enabled = False
        results = run_stage(runtime, options)
        for item in results:
            assert "detected_value" in item.extra
            assert "current_value" not in item.extra
