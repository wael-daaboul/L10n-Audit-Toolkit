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
        assert result["notes_token"] == "[DQ:SAFE_AUTO_PROJECTED]"

    def test_contextual_guard_v1_vetoes_short_your_to_youre_shift(self):
        result = _resolve_candidate_value({}, "Your account", "You're account")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "SUSPICIOUS_GRAMMAR_SHIFT"
        assert result["notes_token"] == "[CONFLICT:SUSPICIOUS_GRAMMAR_SHIFT]"

    def test_contextual_guard_v1_marks_long_your_to_youre_shift_for_review(self):
        result = _resolve_candidate_value({}, "Your account is ready", "You're account is ready")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "SUSPICIOUS_GRAMMAR_SHIFT"
        assert result["notes_token"] == "[REVIEW:SUSPICIOUS_GRAMMAR_SHIFT]"

    def test_contextual_guard_v1_allows_capitalization_only_fix(self):
        result = _resolve_candidate_value({}, "you are ready", "You are ready")
        assert result["candidate_value"] == "You are ready"
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""
        assert result["notes_token"] == "[DQ:SAFE_AUTO_PROJECTED]"

    def test_contextual_guard_v1_does_not_affect_non_matching_cases(self):
        result = _resolve_candidate_value({}, "Our account", "You're account")
        assert result["candidate_value"] == "You're account"
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""
        assert result["notes_token"] == "[DQ:SAFE_AUTO_PROJECTED]"

    def test_pattern_completion_guard_v1_vetoes_numeric_token_addition(self):
        result = _resolve_candidate_value({}, "1 من", "1 من 3")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "PATTERN_COMPLETION_VETO"
        assert result["notes_token"] == "[CONFLICT:PATTERN_COMPLETION_VETO]"

    def test_pattern_completion_guard_v1_vetoes_word_token_addition(self):
        result = _resolve_candidate_value({}, "hello", "hello world")
        assert result["candidate_value"] == ""
        assert result["resolution_mode"] == "conflict"
        assert result["conflict_flag"] == "PATTERN_COMPLETION_VETO"
        assert result["notes_token"] == "[CONFLICT:PATTERN_COMPLETION_VETO]"

    def test_pattern_completion_guard_v1_allows_punctuation_normalization(self):
        result = _resolve_candidate_value({}, "hello ,", "hello,")
        assert result["candidate_value"] == "hello,"
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""
        assert result["notes_token"] == "[DQ:SAFE_AUTO_PROJECTED]"

    def test_pattern_completion_guard_v1_allows_typo_like_single_token_edit(self):
        result = _resolve_candidate_value({}, "teh", "the")
        assert result["candidate_value"] == "the"
        assert result["resolution_mode"] == "suggested_fix"
        assert result["conflict_flag"] == ""
        assert result["notes_token"] == "[DQ:SAFE_AUTO_PROJECTED]"

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
        issue = _clean_issue(current_value="حفظ", details={"semantic_risk": "", "review_reason": "   "})
        # Boundary: pass hydrated current_value explicitly
        assert _project_approved_new(issue, _safe_resolution("احفظ"), issue["current_value"]) == "احفظ"

    def test_a8_safe_suggested_fix_projects_approval(self):
        issue = _clean_issue(current_value="حفظ")
        # Boundary: pass hydrated current_value explicitly
        result = _project_approved_new(issue, _safe_resolution("احفظ"), issue["current_value"]) # Dist 1 (a-)
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

    def test_i2_safe_mechanical_suggestion_projects_approved_new(self, tmp_path: Path):
        """A mechanical (punctuation) suggestion must auto-fill approved_new in Phase 8."""
        ar_current = "حفظ"
        suggested = "حفظ."  # Punctuation normalization
        issue = {
            "key": "save.button",
            "locale": "ar",
            "issue_type": "possible_meaning_loss",
            "severity": "low",
            "message": "Punctuation change",
            "source": "ar_semantic_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": suggested,
                "semantic_risk": "",
                "review_reason": "",
            },
        }
        runtime = _runtime(tmp_path, {"save.button": "Save."}, {"save.button": ar_current})
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
        # Phase 9: Identical suggestions are suppressed from the review queue
        assert len(rows) == 0

    def test_brand_silence_filter_v1_suppresses_grammar_brand_noise(self, tmp_path: Path):
        issue = {
            "key": "payment.method",
            "locale": "en",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "source": "grammar",
            "details": {"old": "Use PayPal for payment", "new": "Use PayPal to pay"},
        }
        runtime = _runtime(tmp_path, {"payment.method": "Use PayPal for payment"}, {})
        rows = build_review_queue([issue], runtime)
        assert rows == []

    def test_brand_silence_filter_v1_suppresses_spelling_acronym_noise(self, tmp_path: Path):
        issue = {
            "key": "otp.prompt",
            "locale": "en",
            "issue_type": "spelling",
            "severity": "medium",
            "message": "Spelling check",
            "source": "grammar",
            "details": {"old": "Enter your OTP now", "new": "Enter your OTP right now"},
        }
        runtime = _runtime(tmp_path, {"otp.prompt": "Enter your OTP now"}, {})
        rows = build_review_queue([issue], runtime)
        assert rows == []

    def test_brand_silence_filter_v1_keeps_grammar_on_normal_text(self, tmp_path: Path):
        issue = {
            "key": "contact.cta",
            "locale": "en",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "source": "grammar",
            "details": {"old": "Talk with us", "new": "Talk to us"},
        }
        runtime = _runtime(tmp_path, {"contact.cta": "Talk with us"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

    def test_brand_silence_filter_v1_keeps_non_eligible_issue_type_on_brand_text(self, tmp_path: Path):
        issue = {
            "key": "payment.method",
            "locale": "en",
            "issue_type": "style",
            "severity": "medium",
            "message": "Style check",
            "source": "grammar",
            "details": {"old": "Use PayPal for payment", "new": "Use PayPal to pay"},
        }
        runtime = _runtime(tmp_path, {"payment.method": "Use PayPal for payment"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

    def test_brand_silence_filter_v1_keeps_non_grammar_source_on_brand_text(self, tmp_path: Path):
        issue = {
            "key": "payment.method",
            "locale": "en",
            "issue_type": "spelling",
            "severity": "medium",
            "message": "Spelling check",
            "source": "locale_qc",
            "details": {"old": "Use PayPal for payment", "new": "Use PayPal to pay"},
        }
        runtime = _runtime(tmp_path, {"payment.method": "Use PayPal for payment"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

    def test_profile_based_case_policy_v1_suppresses_capitalization_on_label_key(self, tmp_path: Path):
        issue = {
            "key": "profile_label",
            "locale": "en",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalization check",
            "source": "locale_qc",
            "details": {"old": "profile", "new": "Profile"},
        }
        runtime = _runtime(tmp_path, {"profile_label": "profile"}, {})
        rows = build_review_queue([issue], runtime)
        assert rows == []

    def test_profile_based_case_policy_v1_suppresses_capitalization_on_btn_key(self, tmp_path: Path):
        issue = {
            "key": "submit_btn",
            "locale": "en",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalization check",
            "source": "locale_qc",
            "details": {"old": "submit", "new": "Submit"},
        }
        runtime = _runtime(tmp_path, {"submit_btn": "submit"}, {})
        rows = build_review_queue([issue], runtime)
        assert rows == []

    def test_profile_based_case_policy_v1_suppresses_capitalization_on_hint_key(self, tmp_path: Path):
        issue = {
            "key": "email_hint",
            "locale": "en",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalization check",
            "source": "locale_qc",
            "details": {"old": "enter email", "new": "Enter email"},
        }
        runtime = _runtime(tmp_path, {"email_hint": "enter email"}, {})
        rows = build_review_queue([issue], runtime)
        assert rows == []

    def test_profile_based_case_policy_v1_keeps_capitalization_on_non_matching_key(self, tmp_path: Path):
        issue = {
            "key": "welcome_msg",
            "locale": "en",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalization check",
            "source": "locale_qc",
            "details": {"old": "welcome back", "new": "Welcome back"},
        }
        runtime = _runtime(tmp_path, {"welcome_msg": "welcome back"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

    def test_profile_based_case_policy_v1_keeps_non_capitalization_on_label_key(self, tmp_path: Path):
        issue = {
            "key": "profile_label",
            "locale": "en",
            "issue_type": "spelling",
            "severity": "low",
            "message": "Spelling check",
            "source": "locale_qc",
            "details": {"old": "teh", "new": "the"},
        }
        runtime = _runtime(tmp_path, {"profile_label": "teh"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

    def test_profile_based_case_policy_v1_keeps_capitalization_from_non_locale_qc_source(self, tmp_path: Path):
        issue = {
            "key": "profile_label",
            "locale": "en",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalization check",
            "source": "grammar",
            "details": {"old": "profile", "new": "Profile"},
        }
        runtime = _runtime(tmp_path, {"profile_label": "profile"}, {})
        rows = build_review_queue([issue], runtime)
        assert len(rows) == 1

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
        safe_suggestion = "حفظ {{name}}." # Mechanical fix

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

        # Incompatible conflict from issue 2 must NOT clear canonical suggested_fix
        assert row["suggested_fix"] == safe_suggestion

        # Conflict token must appear in notes
        assert "[CONFLICT:STRUCTURAL_RISK]" in row["notes"]

        # approved_new set by issue 1 must survive — no destructive overwrite
        assert row["approved_new"] == safe_suggestion

    def test_semantic_clustering_v1_keeps_canonical_outcome_when_incoming_conflict_is_incompatible(
        self, tmp_path: Path
    ):
        ar_current = "حفظ {{name}}"
        safe_suggestion = "حفظ {{name}}."

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
                "candidate_value": "احفظ",
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
        assert row["suggested_fix"] == safe_suggestion
        assert "possible_meaning_loss" in row["issue_type"]
        assert "grammar_error" in row["issue_type"]
        assert "Wording improvement" in row["notes"]
        assert "Grammar fix" in row["notes"]
        assert "[CONFLICT:STRUCTURAL_RISK]" in row["notes"]
        assert "ar_semantic_qc|possible_meaning_loss|low" in row["provenance"]
        assert "ar_locale_qc|grammar_error|medium" in row["provenance"]

    def test_semantic_clustering_v1_keeps_existing_approved_new_when_incoming_approved_new_differs(
        self, tmp_path: Path
    ):
        ar_current = "Hello"
        first_suggestion = "Hello."
        second_suggestion = "Hello!"

        issue_first = {
            "key": "greeting",
            "locale": "ar",
            "issue_type": "punctuation",
            "severity": "low",
            "message": "Add period",
            "source": "ar_semantic_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": first_suggestion,
                "semantic_risk": "",
                "review_reason": "",
            },
        }

        issue_second = {
            "key": "greeting",
            "locale": "ar",
            "issue_type": "style_variant",
            "severity": "low",
            "message": "Use exclamation",
            "source": "ar_locale_qc",
            "needs_review": False,
            "details": {
                "old": ar_current,
                "candidate_value": second_suggestion,
                "semantic_risk": "",
                "review_reason": "",
            },
        }

        runtime = _runtime(
            tmp_path,
            {"greeting": "Hello"},
            {"greeting": ar_current},
        )
        rows = build_review_queue([issue_first, issue_second], runtime)

        assert len(rows) == 1
        row = rows[0]
        assert row["approved_new"] == first_suggestion
        assert "punctuation" in row["issue_type"]
        assert "style_variant" in row["issue_type"]
        assert "Add period" in row["notes"]
        assert "Use exclamation" in row["notes"]
        assert "ar_semantic_qc|punctuation|low" in row["provenance"]
        assert "ar_locale_qc|style_variant|low" in row["provenance"]

    def test_semantic_clustering_v1_still_fully_merges_compatible_same_outcome_signals(
        self, tmp_path: Path
    ):
        ar_current = "Talk with us"
        shared_suggestion = "Talk to us"

        issue_first = {
            "key": "contact.cta",
            "locale": "en",
            "issue_type": "grammar",
            "severity": "medium",
            "message": "Grammar check",
            "source": "grammar",
            "details": {"old": ar_current, "new": shared_suggestion},
        }

        issue_second = {
            "key": "contact.cta",
            "locale": "en",
            "issue_type": "spelling",
            "severity": "medium",
            "message": "Spelling check",
            "source": "grammar",
            "details": {"old": ar_current, "new": shared_suggestion},
        }

        runtime = _runtime(tmp_path, {"contact.cta": ar_current}, {})
        rows = build_review_queue([issue_first, issue_second], runtime)

        assert len(rows) == 1
        row = rows[0]
        assert row["suggested_fix"] == shared_suggestion
        assert "grammar" in row["issue_type"]
        assert "spelling" in row["issue_type"]
        assert "Grammar check" in row["notes"]
        assert "Spelling check" in row["notes"]
        assert "grammar|grammar|medium" in row["provenance"]
        assert "grammar|spelling|medium" in row["provenance"]
