import pytest

from l10n_audit.core.decision_engine import (
    DecisionContext,
    _infer_issue_family,
    evaluate_findings,
    score_finding,
)
from l10n_audit.core.languagetool_layer import LTFinding


def _build_finding(category: str = "grammar", simple: bool = True) -> LTFinding:
    return LTFinding(
        key="k1",
        rule_id="R1",
        issue_category=category,
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=simple,
    )


def test_no_issue_family_feedback_preserves_patch14_behavior() -> None:
    finding = _build_finding()
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"auto_fix": 0.95},
                "rejection_rate_by_route": {"auto_fix": 0.05},
                "avg_confidence_by_route": {"auto_fix": 0.9},
            }
        },
    )

    score = score_finding(finding, ctx)

    assert score["confidence"] == pytest.approx(1.0)
    assert "feedback_autofix_acceptance_bonus" in score["explanation_codes"]
    assert "feedback_grammar_acceptance_bonus" not in score["explanation_codes"]


def test_issue_family_inference_is_deterministic() -> None:
    finding = _build_finding()
    family_a = _infer_issue_family(finding, DecisionContext(findings=[finding], source="en"), "", "", "", "")
    family_b = _infer_issue_family(finding, DecisionContext(findings=[finding], source="en"), "", "", "", "")

    assert family_a == family_b == "grammar"


def test_meaning_loss_family_caution_appears_explicitly() -> None:
    finding = _build_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_issue_family": {"meaning_loss": 0.3},
                "rejection_rate_by_issue_family": {"meaning_loss": 0.5},
                "avg_confidence_by_issue_family": {"meaning_loss": 0.42},
            }
        },
    )

    score = score_finding(finding, ctx)

    assert score["issue_family"] == "meaning_loss"
    assert "feedback_meaning_loss_caution_penalty" in score["explanation_codes"]
    factor = next(
        item for item in score["score_factors"] if item["code"] == "feedback_meaning_loss_caution_penalty"
    )
    assert factor["source"] == "feedback_weighting"
    assert factor["delta"] == pytest.approx(-0.05)


def test_grammar_family_acceptance_bonus_appears_explicitly() -> None:
    finding = _build_finding()
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_issue_family": {"grammar": 0.9},
                "rejection_rate_by_issue_family": {"grammar": 0.05},
                "avg_confidence_by_issue_family": {"grammar": 0.88},
            }
        },
    )

    score = score_finding(finding, ctx)

    assert score["issue_family"] == "grammar"
    assert "feedback_grammar_acceptance_bonus" in score["explanation_codes"]


def test_placeholder_family_feedback_can_influence_confidence() -> None:
    finding = _build_finding()
    finding.placeholder_integrity = "mismatch"
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "rejection_rate_by_issue_family": {"placeholder": 0.4},
                "acceptance_rate_by_issue_family": {"placeholder": 0.45},
                "avg_confidence_by_issue_family": {"placeholder": 0.5},
            }
        },
    )

    score = score_finding(finding, ctx)

    assert score["issue_family"] == "placeholder"
    assert "feedback_placeholder_rejection_penalty" in score["explanation_codes"]


def test_route_feedback_still_exists_alongside_family_feedback() -> None:
    finding = _build_finding()
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"auto_fix": 0.95},
                "rejection_rate_by_route": {"auto_fix": 0.05},
                "avg_confidence_by_route": {"auto_fix": 0.9},
                "acceptance_rate_by_issue_family": {"grammar": 0.9},
                "rejection_rate_by_issue_family": {"grammar": 0.05},
                "avg_confidence_by_issue_family": {"grammar": 0.88},
            }
        },
    )

    score = score_finding(finding, ctx)

    assert "feedback_autofix_acceptance_bonus" in score["explanation_codes"]
    assert "feedback_grammar_acceptance_bonus" in score["explanation_codes"]


def test_family_feedback_does_not_hard_override_route() -> None:
    finding = _build_finding(category="style", simple=False)
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_issue_family": {"style": 0.2},
                "rejection_rate_by_issue_family": {"style": 0.35},
                "avg_confidence_by_issue_family": {"style": 0.4},
            }
        },
    )

    result = evaluate_findings(ctx)

    assert result.ai_review == [finding]
    assert result.auto_fix == []
    assert result.manual_review == []
    assert finding.confidence_score == pytest.approx(0.57)


def test_issue_family_feedback_is_deterministic() -> None:
    metadata = {
        "feedback_metrics": {
            "acceptance_rate_by_route": {"auto_fix": 0.95},
            "rejection_rate_by_route": {"auto_fix": 0.05},
            "avg_confidence_by_route": {"auto_fix": 0.9},
            "acceptance_rate_by_issue_family": {"grammar": 0.9},
            "rejection_rate_by_issue_family": {"grammar": 0.05},
            "avg_confidence_by_issue_family": {"grammar": 0.88},
        }
    }
    finding_a = _build_finding()
    finding_b = _build_finding()

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en", metadata=metadata))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en", metadata=metadata))

    assert score_a == score_b
