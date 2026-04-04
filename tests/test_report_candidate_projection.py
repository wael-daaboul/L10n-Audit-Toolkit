"""Tests for Phase 3 (candidate resolution) and Phase 4 (approval projection)
in report_aggregator.py.

Covers:
  - _resolve_candidate_value
  - _project_approved_new
  - build_review_queue integration (conflict, safe, needs_review, identical)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from l10n_audit.reports.report_aggregator import (
    _project_approved_new,
    _resolve_candidate_value,
    build_review_queue,
)

from conftest import write_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runtime(tmp_path: Path, en: dict, ar: dict):
    """Minimal runtime stub with real locale files on disk."""
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    write_json(en_file, en)
    write_json(ar_file, ar)
    return type(
        "Runtime",
        (),
        {
            "en_file": en_file,
            "ar_file": ar_file,
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        },
    )()


def _safe_resolution(candidate: str = "احفظ") -> dict:
    return {
        "candidate_value": candidate,
        "resolution_mode": "suggested_fix",
        "conflict_flag": "",
        "notes_token": "[SAFE:SUGGESTED_FIX]",
    }


def _clean_issue(**overrides) -> dict:
    base = {
        "needs_review": False,
        "severity": "low",
        "details": {"semantic_risk": "", "review_reason": ""},
    }
    base.update(overrides)
    return base


# ===========================================================================
# Part 1 — Unit tests for _resolve_candidate_value
# ===========================================================================

class TestResolveCandidateValue:

    def test_c1_empty_suggestion(self):
        result = _resolve_candidate_value({}, "حفظ", "")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "no_candidate"
        assert result["conflict_flag"] == "EMPTY_SUGGESTION"
        assert result["notes_token"] == "[NO_CANDIDATE]"

    def test_c1_whitespace_only_suggestion(self):
        result = _resolve_candidate_value({}, "حفظ", "   ")
        assert result["resolution_mode"] == "no_candidate"
        assert result["conflict_flag"] == "EMPTY_SUGGESTION"

    def test_c2_identical_to_current(self):
        result = _resolve_candidate_value({}, "حفظ", "حفظ")
        assert result["candidate_value"] == "حفظ"
        assert result["resolution_mode"] == "current_value"
        assert result["conflict_flag"] == "IDENTICAL_TO_CURRENT"
        assert result["notes_token"] == "[KEEP:CURRENT_VALUE]"

    def test_c2_identical_ignores_surrounding_whitespace(self):
        result = _resolve_candidate_value({}, "حفظ", " حفظ ")
        assert result["resolution_mode"] == "current_value"
        assert result["conflict_flag"] == "IDENTICAL_TO_CURRENT"

    def test_c3_structural_risk_placeholder_mismatch(self):
        result = _resolve_candidate_value({}, "مرحبا {{name}}", "مرحبا")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "STRUCTURAL_RISK"
        assert result["notes_token"] == "[CONFLICT:STRUCTURAL_RISK]"

    def test_c4_structural_risk_tag_mismatch(self):
        result = _resolve_candidate_value({}, "<b>Save</b>", "Save")
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "STRUCTURAL_RISK"

    def test_c4_structural_risk_newline_mismatch(self):
        result = _resolve_candidate_value({}, "line1\nline2", "line1 line2")
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "STRUCTURAL_RISK"

    def test_c5_safe_suggested_fix(self):
        result = _resolve_candidate_value({}, "حفظ", "احفظ")
        assert result["candidate_value"] == "احفظ"
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""
        assert result["notes_token"] == "[SAFE:SUGGESTED_FIX]"

    def test_always_returns_all_four_keys(self):
        for fix in ("", "same", "different", "{{x}} mismatch"):
            result = _resolve_candidate_value({}, "same", fix)
            assert set(result.keys()) == {
                "candidate_value", "resolution_mode", "conflict_flag", "notes_token"
            }

    def test_never_raises_on_none_inputs(self):
        result = _resolve_candidate_value({}, None, None)
        assert isinstance(result["candidate_value"], str)
        assert result["resolution_mode"] == "no_candidate"

    def test_matching_placeholders_not_flagged(self):
        result = _resolve_candidate_value({}, "Hello {{name}}", "Hi {{name}}")
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""


# ===========================================================================
# Part 2 — Unit tests for _project_approved_new
# ===========================================================================

class TestProjectApprovedNew:

    def test_a1_no_candidate_returns_empty(self):
        resolution = {
            "resolution_mode": "no_candidate",
            "candidate_value": "احفظ",
            "conflict_flag": "EMPTY_SUGGESTION",
            "notes_token": "[NO_CANDIDATE]",
        }
        assert _project_approved_new(_clean_issue(), resolution) == ""

    def test_a2_conflict_returns_empty(self):
        resolution = {
            "resolution_mode": "conflict",
            "candidate_value": "",
            "conflict_flag": "STRUCTURAL_RISK",
            "notes_token": "[CONFLICT:STRUCTURAL_RISK]",
        }
        assert _project_approved_new(_clean_issue(), resolution) == ""

    def test_a3_needs_review_true_blocks_approval(self):
        issue = _clean_issue(needs_review=True)
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a4_high_severity_blocks_approval(self):
        issue = _clean_issue(severity="high")
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a5_critical_severity_blocks_approval(self):
        issue = _clean_issue(severity="critical")
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a4_severity_check_is_case_insensitive(self):
        issue = _clean_issue(severity="HIGH")
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a6_high_semantic_risk_blocks_approval(self):
        issue = _clean_issue(details={"semantic_risk": "high", "review_reason": ""})
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a6_semantic_risk_case_insensitive(self):
        issue = _clean_issue(details={"semantic_risk": "HIGH", "review_reason": ""})
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a7_review_reason_blocks_approval(self):
        issue = _clean_issue(details={"semantic_risk": "", "review_reason": "meaning changed"})
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_a7_whitespace_only_review_reason_does_not_block(self):
        issue = _clean_issue(details={"semantic_risk": "", "review_reason": "   "})
        assert _project_approved_new(issue, _safe_resolution()) == "احفظ"

    def test_a8_safe_suggested_fix_projects_approval(self):
        issue = _clean_issue()
        result = _project_approved_new(issue, _safe_resolution("احفظ"))
        assert result == "احفظ"

    @pytest.mark.parametrize("truthy_str", ["true", "yes", "1", "True", "YES"])
    def test_a9_truthy_string_needs_review_blocks_approval(self, truthy_str: str):
        issue = _clean_issue(needs_review=truthy_str)
        assert _project_approved_new(issue, _safe_resolution()) == ""

    def test_current_value_mode_does_not_auto_approve(self):
        resolution = {
            "resolution_mode": "current_value",
            "candidate_value": "حفظ",
            "conflict_flag": "IDENTICAL_TO_CURRENT",
            "notes_token": "[KEEP:CURRENT_VALUE]",
        }
        assert _project_approved_new(_clean_issue(), resolution) == ""

    def test_never_returns_none(self):
        assert _project_approved_new(None, {}) is not None  # type: ignore[arg-type]
        assert _project_approved_new({}, None) is not None  # type: ignore[arg-type]


# ===========================================================================
# Part 3 — Integration tests for build_review_queue
# ===========================================================================

class TestBuildReviewQueueIntegration:

    def test_i1_conflict_clears_suggested_fix_and_adds_notes_token(self, tmp_path: Path):
        """A structural mismatch in the suggestion must clear suggested_fix and stamp the notes."""
        # current AR value has a placeholder; suggested (from AI) drops it → structural risk
        ar_current = "مرحبا {{name}}"
        en_val = "Hello {{name}}"
        issue = {
            "key": "greeting",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "medium",
            "message": "Meaning loss",
            "source": "ar_semantic_qc",
            "details": {"old": ar_current, "new": "مرحبا", "candidate_value": "مرحبا"},
            "suggested_fix": "مرحبا",
        }
        runtime = _runtime(tmp_path, {"greeting": en_val}, {"greeting": ar_current})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1
        row = rows[0]
        assert row["suggested_fix"] == ""
        assert "[CONFLICT:STRUCTURAL_RISK]" in row["notes"]

    def test_i2_safe_suggestion_projects_approved_new(self, tmp_path: Path):
        """A clean low-risk suggestion with no review blockers must auto-fill approved_new."""
        ar_current = "حفظ"
        suggested = "احفظ الملف"
        issue = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "low",
            "message": "Slight wording improvement",
            "source": "ar_semantic_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": suggested,
                "semantic_risk": "",
                "review_reason": "",
            },
        }
        runtime = _runtime(tmp_path, {"save.button": "Save File"}, {"save.button": ar_current})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1
        row = rows[0]
        assert row["suggested_fix"] == suggested
        assert row["approved_new"] == suggested

    def test_i3_needs_review_prevents_approved_new_projection(self, tmp_path: Path):
        """needs_review=True must block approved_new even when the fix is structurally safe."""
        ar_current = "حفظ"
        suggested = "احفظ الملف"
        issue = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "low",
            "message": "Needs human check",
            "source": "ar_semantic_qc",
            "needs_review": True,
            "details": {
                "old": ar_current,
                "candidate_value": suggested,
                "semantic_risk": "",
                "review_reason": "",
            },
        }
        runtime = _runtime(tmp_path, {"save.button": "Save File"}, {"save.button": ar_current})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1
        row = rows[0]
        assert row["suggested_fix"] == suggested
        assert row["approved_new"] == ""

    def test_i4_identical_suggestion_stamps_keep_token_and_does_not_auto_approve(self, tmp_path: Path):
        """When suggested == current, the row must get [KEEP:CURRENT_VALUE] in notes and empty approved_new."""
        ar_current = "حفظ"
        issue = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "low",
            "message": "No change needed",
            "source": "ar_semantic_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": ar_current,   # identical to current
                "semantic_risk": "",
                "review_reason": "",
            },
        }
        runtime = _runtime(tmp_path, {"save.button": "Save"}, {"save.button": ar_current})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1
        row = rows[0]
        assert "[KEEP:CURRENT_VALUE]" in row["notes"]
        # current_value mode should not produce an auto-approval
        assert row["approved_new"] == ""

    def test_merge_path_conflict_clears_existing_suggested_fix_but_preserves_existing_approved_new(
        self, tmp_path: Path
    ):
        """Two issues share (key, locale).

        Issue 1 (safe):  produces suggested_fix="احفظ", approved_new="احفظ"
        Issue 2 (conflict): {{name}} placeholder dropped → STRUCTURAL_RISK

        Expected final row:
          - suggested_fix == ""          (cleared by conflict)
          - notes contains [CONFLICT:STRUCTURAL_RISK]
          - approved_new == "احفظ"       (preserved — no destructive overwrite)
        """
        ar_current = "حفظ {{name}}"
        safe_suggestion = "احفظ الملف"

        # Issue 1 — safe: different text, no structural risk, no review blockers
        issue_safe = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "low",
            "message": "Wording improvement",
            "source": "ar_semantic_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": safe_suggestion,
                "semantic_risk": "",
                "review_reason": "",
            },
        }

        # Issue 2 — conflict: drops the {{name}} placeholder
        issue_conflict = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "grammar_error",
            "severity": "medium",
            "message": "Grammar fix",
            "source": "ar_locale_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": "احفظ",   # missing {{name}} → structural risk
                "semantic_risk": "",
                "review_reason": "",
            },
            "suggested_fix": "احفظ",
        }

        runtime = _runtime(
            tmp_path,
            {"save.button": "Save {{name}}"},
            {"save.button": ar_current},
        )
        rows = build_review_queue([issue_safe, issue_conflict], runtime)

        assert len(rows) == 1
        row = rows[0]

        # Conflict from issue 2 must clear suggested_fix
        assert row["suggested_fix"] == ""

        # Conflict token must appear in notes
        assert "[CONFLICT:STRUCTURAL_RISK]" in row["notes"]

        # approved_new set by issue 1 must survive — no destructive overwrite
        assert row["approved_new"] == safe_suggestion
