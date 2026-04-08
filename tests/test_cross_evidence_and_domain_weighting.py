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


def test_cross_evidence_meaning_loss_placeholder_penalty_applies() -> None:
    finding = _build_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    finding.placeholder_integrity = "mismatch"

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert "cross_evidence_meaning_loss_placeholder_penalty" in score["explanation_codes"]
    feedback_sources = score["confidence_evidence"]["feedback_sources"]
    assert {
        "source": "cross_evidence",
        "delta": -0.03,
        "reason": "cross_evidence_meaning_loss_placeholder_penalty",
    } in feedback_sources


def test_no_interaction_when_only_one_signal_exists() -> None:
    finding = _build_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert "cross_evidence_meaning_loss_placeholder_penalty" not in score["explanation_codes"]


def test_structural_low_confidence_penalty_applies() -> None:
    finding = _build_finding(category="complex", simple=False)
    finding.structural_consistency = "shape_mismatch"

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert score["confidence"] == pytest.approx(0.38)
    assert "cross_evidence_structural_low_confidence_penalty" in score["explanation_codes"]


def test_domain_penalty_applies_for_legal_domain() -> None:
    finding = _build_finding()

    score = score_finding(
        finding,
        DecisionContext(findings=[finding], source="en", metadata={"domain": "legal"}),
    )

    assert "domain_low_tolerance_penalty" in score["explanation_codes"]
    assert score["confidence"] == pytest.approx(0.98)


def test_domain_bonus_applies_for_marketing_domain() -> None:
    finding = _build_finding()

    score = score_finding(
        finding,
        DecisionContext(findings=[finding], source="en", metadata={"domain": "marketing"}),
    )

    assert "domain_high_tolerance_bonus" in score["explanation_codes"]
    assert score["confidence"] == pytest.approx(1.0)


def test_no_domain_means_no_domain_adjustment() -> None:
    finding = _build_finding()

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert "domain_low_tolerance_penalty" not in score["explanation_codes"]
    assert "domain_high_tolerance_bonus" not in score["explanation_codes"]


def test_interactions_do_not_override_route() -> None:
    finding = _build_finding(category="style", simple=False)
    finding.structural_consistency = "shape_mismatch"
    score = score_finding(
        finding,
        DecisionContext(findings=[finding], source="en", metadata={"domain": "legal"}),
    )

    result = evaluate_findings(
        DecisionContext(findings=[finding], source="en", metadata={"domain": "legal"})
    )

    assert score["confidence"] == pytest.approx(0.46)
    assert result.ai_review == [finding]
    assert result.auto_fix == []
    assert result.manual_review == []


def test_cross_evidence_and_domain_scoring_is_deterministic() -> None:
    metadata = {"domain": "finance"}
    finding_a = _build_finding()
    finding_b = _build_finding()
    for finding in (finding_a, finding_b):
        finding.semantic_risk = "high"
        finding.semantic_evidence = {
            "shape_preserved": True,
            "action_preserved": True,
            "entity_alignment_ok": True,
        }
        finding.placeholder_integrity = "missing"
        finding.glossary_alignment = "violation"

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en", metadata=metadata))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en", metadata=metadata))

    assert score_a == score_b


def test_combined_new_adjustments_remain_bounded() -> None:
    finding = _build_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    finding.placeholder_integrity = "missing"
    finding.glossary_alignment = "violation"

    score = score_finding(
        finding,
        DecisionContext(findings=[finding], source="en", metadata={"domain": "security"}),
    )

    feedback_sources = score["confidence_evidence"]["feedback_sources"]
    new_adjustment_total = sum(
        entry["delta"]
        for entry in feedback_sources
        if entry["source"] in {"cross_evidence", "domain_weighting"}
    )

    assert new_adjustment_total == pytest.approx(-0.07)
    assert abs(new_adjustment_total) <= 0.1
