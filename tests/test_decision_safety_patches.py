import pytest
from unittest.mock import MagicMock, patch
from l10n_audit.models import AuditOptions, AIReview
from l10n_audit.audits.ai_review import run_stage
from l10n_audit.core.mock_ai_provider import MockAIProvider
from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
from l10n_audit.fixes.fix_merger import export_review_queue
from pathlib import Path

def _runtime(tmp_path):
    rt = type(
        "Runtime",
        (),
        {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
            "results_dir": tmp_path / "Results",
            "metadata": {},
        },
    )()
    rt.results_dir.mkdir(parents=True, exist_ok=True)
    return rt


@patch("l10n_audit.audits.ai_review.load_issues")
@patch("l10n_audit.audits.ai_review.load_locale_mapping")
@patch("l10n_audit.core.ai_factory.get_ai_provider")
def test_short_ambiguous_no_context_produces_review_finding(mock_get_provider, mock_load_locale, mock_load_issues, tmp_path):
    runtime = _runtime(tmp_path)
    options = AuditOptions(ai_review=AIReview(enabled=True, api_key_env="OPENAI_API_KEY"))

    # Issue with short label, no glossary, no context
    mock_load_issues.return_value = [
        {
            "key": "btn.ok",
            "issue_type": "semantic_mismatch",
            "message": "Verify translation",
            "context": "",
        }
    ]
    mock_load_locale.side_effect = [
        {"btn.ok": "Ok"},      # EN
        {"btn.ok": "موافق"},  # AR
    ]

    mock_provider = MagicMock()
    mock_get_provider.return_value = mock_provider

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={}):
        results = run_stage(runtime, options, ai_provider=mock_provider)

    # Verify AI was NOT invoked
    assert mock_provider.review_batch.call_count == 0

    # Verify we still get a review-required finding
    assert len(results) == 1
    issue = results[0]
    assert issue.key == "btn.ok"
    assert issue.needs_review is True
    
    metadata = issue.extra.get("_raw_metadata", {}).get("extra", {})
    assert metadata.get("ai_outcome_decision") == "review"
    assert metadata.get("semantic_gate_status") == "suspicious"
    assert "short_ambiguous_no_context" in metadata.get("semantic_reason_codes", [])


@patch("l10n_audit.audits.ai_review.load_issues")
@patch("l10n_audit.audits.ai_review.load_locale_mapping")
def test_ai_same_text_produces_review_finding(mock_load_locale, mock_load_issues, tmp_path):
    runtime = _runtime(tmp_path)
    options = AuditOptions(ai_review=AIReview(enabled=True, api_key_env="OPENAI_API_KEY"))

    mock_load_issues.return_value = [
        {
            "key": "msg.welcome",
            "issue_type": "semantic_mismatch",
            "message": "Welcome greeting",
            "context": "Welcome header screen",
        }
    ]
    mock_load_locale.side_effect = [
        {"msg.welcome": "Welcome back user"},  # EN
        {"msg.welcome": "أهلاً بك مجدداً"},       # AR
    ]

    # AI returns the same text as current translation
    mock_provider = MockAIProvider(
        fixes=[
            {
                "key": "msg.welcome",
                "suggestion": "أهلاً بك مجدداً",  # identical to target
                "reason": "Correct as is",
            }
        ]
    )

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={}):
        results = run_stage(runtime, options, ai_provider=mock_provider)

    # Verify we get a review-required finding due to identical suggestion (uncertainty)
    assert len(results) == 1
    issue = results[0]
    assert issue.key == "msg.welcome"
    assert issue.needs_review is True
    
    metadata = issue.extra.get("_raw_metadata", {}).get("extra", {})
    assert metadata.get("ai_outcome_decision") == "review"
    assert metadata.get("semantic_gate_status") == "suspicious"
    assert "ai_returned_same_text" in metadata.get("semantic_reason_codes", [])


def test_empty_candidate_plan_and_review_queue(tmp_path):
    runtime = _runtime(tmp_path)

    # Finding with no suggestion/candidate
    issue = {
        "key": "msg.untranslated",
        "source": "ai_review",
        "issue_type": "ai_suggestion",
        "locale": "ar",
        "verified": False,
        "needs_review": True,
        "message": "Issue message",
        "generated_at": "2026-06-01T20:45:00",
        "details": {
            "old": "Untranslated text",
            "generated_at": "2026-06-01T20:45:00",
            # No candidate/new suggestion
        }
    }

    # Build fix plan
    plan = build_fix_plan([issue], runtime=runtime)
    assert len(plan) == 1
    plan_item = plan[0]
    assert plan_item["key"] == "msg.untranslated"
    assert plan_item["candidate_value"] == ""
    assert plan_item["classification"] == "review_required"

    # Export review queue
    out_file = tmp_path / "review_queue.json"
    exported_path = export_review_queue(plan, runtime, out_file)
    assert exported_path.exists()

    # Ensure no rows were rejected
    assert len(runtime.metadata.get("invalid_review_rows", [])) == 0
