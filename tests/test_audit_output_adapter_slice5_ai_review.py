"""
tests/test_audit_output_adapter_slice5_ai_review.py
====================================================

Phase 7C Slice 5 — focused tests for ai_review adapter wiring.

Covers:
  1.  ai_review.run_stage() returns AuditIssue objects
  2.  target → detected_value (via shim)
  3.  suggestion → candidate_value (via adapter 3rd fallback)
  4.  verified preserved in _raw_metadata
  5.  original_source preserved in _raw_metadata
  6.  target preserved in _raw_metadata
  7.  no current_value emitted
  8.  audit_source == "ai_review" in extra
  9.  locale == "ar" in AuditIssue.locale
  10. issue_type == "ai_suggestion"
  11. issue_from_dict() still produces valid AuditIssue
  12. live lookup / prompt behavior path unchanged (verified via MockAIProvider)
  13. _ai_review_to_adapter_shape unit-level: additive mapping
  14. Slice 4 regression guard
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

def _make_ai_review_runtime(tmp_path: Path):
    """Minimal runtime for ai_review.run_stage() with MockAIProvider."""
    en_json = tmp_path / "en.json"
    ar_json = tmp_path / "ar.json"
    en_json.write_text(
        json.dumps({"greeting": "Hello World", "farewell": "Goodbye"}),
        encoding="utf-8",
    )
    ar_json.write_text(
        json.dumps({"greeting": "مرحبا بك", "farewell": "وداعا"}),
        encoding="utf-8",
    )
    glossary_json = tmp_path / "config" / "glossary.json"
    (tmp_path / "config").mkdir(exist_ok=True)
    glossary_json.write_text(json.dumps({"terms": [], "rules": {}}), encoding="utf-8")

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


def _make_ai_review_options(batch_size: int = 50):
    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.model = "gpt-4o-mini"
    options.ai_review.provider = "litellm"
    options.ai_review.batch_size = batch_size
    options.ai_review.translate_missing = False
    options.ai_review.short_label_threshold = 3
    options.write_reports = False
    options.suppression.include_per_tool_csv = False
    options.suppression.include_per_tool_xlsx = False
    options.effective_output_dir = lambda base: base
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = {}
    return options


def _make_mock_provider(fixes: list[dict] | None = None):
    from l10n_audit.core.mock_ai_provider import MockAIProvider
    return MockAIProvider(fixes=fixes or [])


def _make_previous_issues(key: str = "greeting") -> list[dict]:
    """Minimal upstream issue dicts that pass the enforcement/routing gate."""
    return [
        {
            "key": key,
            "issue_type": "ar_qc",
            "severity": "medium",
            "message": "Arabic text may need review.",
            "context": "Home screen greeting label",
            "decision": {
                "route": "ai_review",
                "confidence": 0.7,
                "risk": "low",
                "engine_version": "v3",
            },
        }
    ]


# ---------------------------------------------------------------------------
# Core fixture: non-empty result driven by MockAIProvider
# ---------------------------------------------------------------------------

@pytest.fixture()
def ai_review_results(tmp_path):
    """Run ai_review.run_stage() with a MockAIProvider that returns one fix."""
    from unittest.mock import patch
    from l10n_audit.audits.ai_review import run_stage
    runtime = _make_ai_review_runtime(tmp_path)
    options = _make_ai_review_options()
    mock_provider = _make_mock_provider(fixes=[
        {
            "key": "greeting",
            "suggestion": "أهلاً بك",
            "reason": "More formal greeting",
        }
    ])
    previous_issues = _make_previous_issues("greeting")
    # Patch validate_ai_config to bypass API key requirement when using MockAIProvider.
    # The live AI path (validate_ai_config → provider factory) is irrelevant here;
    # ai_provider is injected directly.
    _fake_config = {"api_key": "test", "model": "gpt-4o-mini", "api_base": "http://localhost"}
    with patch("l10n_audit.core.validators.validate_ai_config", return_value=_fake_config):
        return run_stage(
            runtime,
            options,
            ai_provider=mock_provider,
            previous_issues=previous_issues,
        )


# ---------------------------------------------------------------------------
# 1. Return type
# ---------------------------------------------------------------------------

class TestAiReviewReturnType:

    def test_returns_list(self, ai_review_results):
        assert isinstance(ai_review_results, list)

    def test_items_are_audit_issue(self, ai_review_results):
        from l10n_audit.models import AuditIssue
        for item in ai_review_results:
            assert isinstance(item, AuditIssue), (
                f"Expected AuditIssue, got {type(item)!r}"
            )

    def test_at_least_one_result(self, ai_review_results):
        """The MockAIProvider returns one fix for 'greeting'."""
        assert ai_review_results, "Expected at least one AI review result"


# ---------------------------------------------------------------------------
# 2. target → detected_value (via shim)
# ---------------------------------------------------------------------------

class TestDetectedValueAiReview:

    def test_detected_value_in_extra(self, ai_review_results):
        for item in ai_review_results:
            assert "detected_value" in item.extra, (
                f"'detected_value' missing from extra for key={item.key!r}"
            )

    def test_detected_value_is_string(self, ai_review_results):
        for item in ai_review_results:
            assert isinstance(item.extra["detected_value"], str)

    def test_detected_value_is_live_ar_value(self, ai_review_results):
        """target ('مرحبا بك') becomes detected_value."""
        for item in ai_review_results:
            if item.key == "greeting":
                assert item.extra["detected_value"] == "مرحبا بك", (
                    f"detected_value should be live AR text, got {item.extra['detected_value']!r}"
                )

    def test_old_not_at_top_level_in_extra(self, ai_review_results):
        for item in ai_review_results:
            assert "old" not in item.extra, (
                f"'old' must be remapped to 'detected_value', not remain in extra"
            )


# ---------------------------------------------------------------------------
# 3. suggestion → candidate_value (via adapter 3rd fallback)
# ---------------------------------------------------------------------------

class TestCandidateValueAiReview:

    def test_candidate_value_in_extra(self, ai_review_results):
        for item in ai_review_results:
            assert "candidate_value" in item.extra, (
                f"'candidate_value' missing from extra for key={item.key!r}"
            )

    def test_candidate_value_is_ai_suggestion(self, ai_review_results):
        """suggestion ('أهلاً بك') becomes candidate_value."""
        for item in ai_review_results:
            if item.key == "greeting":
                assert item.extra["candidate_value"] == "أهلاً بك", (
                    f"candidate_value should be AI suggestion, got {item.extra['candidate_value']!r}"
                )

    def test_suggestion_not_at_top_level_in_extra(self, ai_review_results):
        """suggestion must be consumed by adapter, not remain as top-level extra key."""
        for item in ai_review_results:
            assert "suggestion" not in item.extra, (
                f"'suggestion' must be remapped to 'candidate_value', not remain in extra"
            )


# ---------------------------------------------------------------------------
# 4. verified preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestVerifiedPreserved:

    def test_raw_metadata_present(self, ai_review_results):
        for item in ai_review_results:
            assert "_raw_metadata" in item.extra, (
                f"_raw_metadata missing for key={item.key!r}"
            )

    def test_verified_in_raw_metadata(self, ai_review_results):
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "verified" in meta, (
                f"'verified' missing from _raw_metadata for key={item.key!r}"
            )

    def test_verified_is_true(self, ai_review_results):
        """verify_batch_fixes only appends rows where verified=True."""
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert meta.get("verified") is True


# ---------------------------------------------------------------------------
# 5. original_source preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestOriginalSourcePreserved:

    def test_original_source_in_raw_metadata(self, ai_review_results):
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "original_source" in meta, (
                f"'original_source' missing from _raw_metadata for key={item.key!r}"
            )

    def test_original_source_is_string(self, ai_review_results):
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert isinstance(meta.get("original_source"), str)


# ---------------------------------------------------------------------------
# 6. target preserved in _raw_metadata
# ---------------------------------------------------------------------------

class TestTargetPreserved:

    def test_target_in_raw_metadata(self, ai_review_results):
        """target was shimmed to 'old' but must still be preserved in _raw_metadata."""
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "target" in meta, (
                f"'target' missing from _raw_metadata for key={item.key!r}"
            )

    def test_target_matches_detected_value(self, ai_review_results):
        """target and detected_value must be the same value (shim copies it)."""
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert meta.get("target") == item.extra.get("detected_value"), (
                f"target in _raw_metadata should match detected_value for key={item.key!r}"
            )


# ---------------------------------------------------------------------------
# 7. current_value must NOT appear
# ---------------------------------------------------------------------------

class TestCurrentValueAbsenceAiReview:

    def test_no_current_value_in_extra(self, ai_review_results):
        for item in ai_review_results:
            assert "current_value" not in item.extra

    def test_no_current_value_in_raw_metadata(self, ai_review_results):
        for item in ai_review_results:
            meta = item.extra.get("_raw_metadata", {})
            assert "current_value" not in meta


# ---------------------------------------------------------------------------
# 8. audit_source and locale
# ---------------------------------------------------------------------------

class TestAuditSourceLocaleAiReview:

    def test_audit_source_equals_ai_review(self, ai_review_results):
        for item in ai_review_results:
            assert item.extra.get("audit_source") == "ai_review", (
                f"Expected audit_source='ai_review', got {item.extra.get('audit_source')!r}"
            )

    def test_locale_is_ar(self, ai_review_results):
        for item in ai_review_results:
            assert item.locale == "ar", (
                f"Expected locale='ar', got {item.locale!r}"
            )


# ---------------------------------------------------------------------------
# 9. issue_type preserved
# ---------------------------------------------------------------------------

class TestIssueTypeAiReview:

    def test_issue_type_is_ai_suggestion(self, ai_review_results):
        """Existing normalised comprehension sets issue_type='ai_suggestion'."""
        for item in ai_review_results:
            assert item.issue_type == "ai_suggestion", (
                f"Expected issue_type='ai_suggestion', got {item.issue_type!r}"
            )


# ---------------------------------------------------------------------------
# 10. MockAIProvider: live lookup path unchanged
# ---------------------------------------------------------------------------

class TestLiveLookupPathUnchanged:

    def test_mock_provider_called_with_batch(self, tmp_path):
        """MockAIProvider.last_batch must contain current_translation from live AR lookup."""
        from unittest.mock import patch
        from l10n_audit.audits.ai_review import run_stage
        runtime = _make_ai_review_runtime(tmp_path)
        options = _make_ai_review_options()
        mock = _make_mock_provider(fixes=[
            {"key": "greeting", "suggestion": "أهلاً بك", "reason": "test"}
        ])
        _fake_config = {"api_key": "test", "model": "gpt-4o-mini", "api_base": "http://localhost"}
        with patch("l10n_audit.core.validators.validate_ai_config", return_value=_fake_config):
            run_stage(
                runtime, options, ai_provider=mock,
                previous_issues=_make_previous_issues("greeting"),
            )
        assert mock.call_count >= 1
        batch = mock.last_batch
        assert len(batch) >= 1
        item = next((b for b in batch if b.get("key") == "greeting"), None)
        assert item is not None, "Expected 'greeting' key in batch"
        assert "current_translation" in item, (
            "'current_translation' must still be present in prompt batch (live lookup not removed)"
        )
        assert item["current_translation"] == "مرحبا بك", (
            "current_translation must equal live AR value from ar.json"
        )

    def test_empty_result_when_no_previous_issues(self, tmp_path):
        """With no previous issues, run_stage returns [] without calling provider."""
        from unittest.mock import patch
        from l10n_audit.audits.ai_review import run_stage
        runtime = _make_ai_review_runtime(tmp_path)
        options = _make_ai_review_options()
        mock = _make_mock_provider()
        _fake_config = {"api_key": "test", "model": "gpt-4o-mini", "api_base": "http://localhost"}
        with patch("l10n_audit.core.validators.validate_ai_config", return_value=_fake_config):
            result = run_stage(runtime, options, ai_provider=mock, previous_issues=[])
        assert result == []
        assert mock.call_count == 0


# ---------------------------------------------------------------------------
# 11. _ai_review_to_adapter_shape unit-level
# ---------------------------------------------------------------------------

class TestAiReviewShim:
    """Direct unit tests for the shim + adapter on a verify_batch_fixes-shaped row."""

    def _ai_fix_row(self, **overrides) -> dict:
        """Row as produced by verify_batch_fixes after normalised comprehension."""
        row = {
            "key": "greeting",
            "verified": True,
            "issue_type": "ai_suggestion",
            "severity": "info",
            "message": "AI Suggestion: More formal greeting",
            "source": "ai_review",          # already overwritten by normalised comprehension
            "original_source": "Hello World",
            "target": "مرحبا بك",           # live AR value
            "suggestion": "أهلاً بك",       # AI-proposed fix
            "extra": {"verified": True},
        }
        row.update(overrides)
        return row

    def _shim(self, row: dict) -> dict:
        """Replicate the shim defined inside run_stage."""
        return {**row, "old": row.get("target", "")}

    def test_shim_adds_old_from_target(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        assert shimmed["old"] == "مرحبا بك"

    def test_shim_preserves_target(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        assert shimmed["target"] == "مرحبا بك"

    def test_shim_preserves_suggestion(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        assert shimmed["suggestion"] == "أهلاً بك"

    def test_shim_preserves_verified(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        assert shimmed["verified"] is True

    def test_shim_preserves_original_source(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        assert shimmed["original_source"] == "Hello World"

    def test_adapter_target_maps_to_detected_value(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["detected_value"] == "مرحبا بك"

    def test_adapter_suggestion_maps_to_candidate_value(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["candidate_value"] == "أهلاً بك"

    def test_adapter_verified_in_raw_metadata(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["_raw_metadata"]["verified"] is True

    def test_adapter_original_source_in_raw_metadata(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["_raw_metadata"]["original_source"] == "Hello World"

    def test_adapter_target_in_raw_metadata(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["_raw_metadata"]["target"] == "مرحبا بك"

    def test_adapter_no_current_value(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert "current_value" not in result

    def test_adapter_old_not_at_top_level(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert "old" not in result

    def test_adapter_suggestion_not_at_top_level(self):
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert "suggestion" not in result

    def test_issue_from_dict_works(self):
        from l10n_audit.models import AuditIssue, issue_from_dict
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        normalized = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        issue = issue_from_dict(normalized)
        assert isinstance(issue, AuditIssue)
        assert issue.locale == "ar"
        assert issue.issue_type == "ai_suggestion"

    def test_empty_target_gives_empty_detected_value(self):
        row = self._ai_fix_row(target="")
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["detected_value"] == ""

    def test_issue_type_ai_suggestion_preserved(self):
        """The normalised comprehension sets issue_type='ai_suggestion'; adapter must not clobber it."""
        row = self._ai_fix_row()
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        assert result["issue_type"] == "ai_suggestion"

    def test_source_overwrite_preserved(self):
        """The pre-existing source='ai_review' string from the normalised comprehension
        must survive through the adapter (it's in _DOWNSTREAM_KNOWN / falls into extra)."""
        row = self._ai_fix_row()  # source is already "ai_review" in normalised row
        shimmed = self._shim(row)
        result = normalize_audit_finding(shimmed, audit_source="ai_review", locale="ar")
        # source passes through _DOWNSTREAM_KNOWN → survives in normalised dict
        assert result.get("source") == "ai_review"


# ---------------------------------------------------------------------------
# 12. Regression guard — Slice 4 (terminology) unaffected
# ---------------------------------------------------------------------------

class TestSlice4UnaffectedBySlice5:

    def test_terminology_shim_still_works(self):
        """The terminology shim + adapter must be unaffected after Slice 5."""
        from l10n_audit.core.audit_output_adapter import normalize_audit_finding
        row = {
            "key": "error.generic",
            "violation_type": "forbidden_term",
            "issue_type": "terminology_violation",
            "severity": "high",
            "fix_mode": "review_required",
            "message": "Uses forbidden term.",
            "arabic_value": "حدثت مشكلة.",
            "expected_ar": "خطأ",
            "found_ar": "مشكلة",
            "english_value": "An error occurred.",
            "source": "terminology",
            "context_type": "", "ui_surface": "", "text_role": "",
            "action_hint": "", "audience_hint": "", "context_flags": "",
            "semantic_risk": "low", "lt_signals": "{}", "review_reason": "",
        }
        shimmed = {
            **row,
            "old": row.get("arabic_value", ""),
            "new": row.get("expected_ar", ""),
        }
        result = normalize_audit_finding(shimmed, audit_source="terminology_audit", locale="ar")
        assert result["detected_value"] == "حدثت مشكلة."
        assert result["candidate_value"] == "خطأ"
        assert result["_raw_metadata"]["english_value"] == "An error occurred."
        assert "current_value" not in result
