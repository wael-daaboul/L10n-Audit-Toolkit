import pytest

from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings, score_finding
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


def test_no_feedback_preserves_legacy_behavior() -> None:
    finding = _build_finding()

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert score["confidence"] == pytest.approx(1.0)
    assert "feedback_weighting" not in score["evidence_sources"]


def test_feedback_source_appears_explicitly() -> None:
    finding = _build_finding()
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"auto_fix": 0.95},
                "rejection_rate_by_route": {"auto_fix": 0.05},
                "avg_confidence_by_route": {"auto_fix": 0.92},
            }
        },
    )

    score = score_finding(finding, ctx)

    feedback_factor = next(
        factor for factor in score["score_factors"] if factor["code"] == "feedback_autofix_acceptance_bonus"
    )
    assert feedback_factor["source"] == "feedback_weighting"
    assert feedback_factor["delta"] == pytest.approx(0.04)
    assert score["issue_family"] == "grammar"
    assert score["confidence"] == pytest.approx(1.0)


def test_feedback_deltas_are_bounded_and_conservative() -> None:
    finding = _build_finding(category="complex", simple=False)
    finding.suggested_text = ""
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"manual_review": 0.2},
                "rejection_rate_by_route": {"manual_review": 0.7},
                "avg_confidence_by_route": {"manual_review": 0.3},
            }
        },
    )

    score = score_finding(finding, ctx)
    feedback_factors = [factor for factor in score["score_factors"] if factor["source"] == "feedback_weighting"]

    assert feedback_factors
    assert all(-0.08 <= float(factor["delta"]) <= 0.08 for factor in feedback_factors)
    assert score["confidence"] == pytest.approx(0.08)


def test_feedback_does_not_hard_override_route() -> None:
    finding = _build_finding(category="style", simple=False)
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"ai_review": 0.85},
                "rejection_rate_by_route": {"ai_review": 0.05},
                "avg_confidence_by_route": {"ai_review": 0.6},
            }
        },
    )

    result = evaluate_findings(ctx)

    assert result.ai_review == [finding]
    assert result.auto_fix == []
    assert result.manual_review == []
    assert finding.confidence_score == pytest.approx(0.63)


def test_decision_explanation_includes_feedback_weighting() -> None:
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

    evaluate_findings(ctx)
    explanation = finding._decision_explanation

    assert "feedback_weighting" in explanation["evidence_sources"]
    feedback_summary = next(item for item in explanation["contribution_summary"] if item["source"] == "feedback_weighting")
    assert feedback_summary["codes"] == ["feedback_autofix_acceptance_bonus"]


def test_feedback_scoring_is_deterministic() -> None:
    ctx_metadata = {
        "feedback_metrics": {
            "acceptance_rate_by_route": {"auto_fix": 0.95},
            "rejection_rate_by_route": {"auto_fix": 0.25},
            "avg_confidence_by_route": {"auto_fix": 0.9},
        }
    }
    finding_a = _build_finding()
    finding_b = _build_finding()

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en", metadata=ctx_metadata))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en", metadata=ctx_metadata))

    assert score_a == score_b
