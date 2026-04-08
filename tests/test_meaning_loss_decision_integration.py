from l10n_audit.core.decision_engine import DecisionContext, RouteAction, evaluate_findings, score_finding
from l10n_audit.core.languagetool_layer import LTFinding


def _semantic_finding() -> LTFinding:
    finding = LTFinding(
        key="k1",
        rule_id="R1",
        issue_category="grammar",
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=True,
    )
    return finding


def test_shape_action_entity_penalties_appear_explicitly() -> None:
    finding = _semantic_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": False,
        "action_preserved": False,
        "entity_alignment_ok": False,
    }

    score = score_finding( finding, DecisionContext(findings=[finding], source="en"))

    assert "semantic_shape_mismatch_penalty" in score["explanation_codes"]
    assert "semantic_action_loss_penalty" in score["explanation_codes"]
    assert "semantic_entity_mismatch_penalty" in score["explanation_codes"]


def test_no_hard_route_shortcut_semantic_penalties_flow_through_confidence() -> None:
    finding = _semantic_finding()
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"))

    assert finding.confidence_score == 0.7
    assert result.ai_review == [finding]
    assert result.manual_review == []
    assert result.auto_fix == []


def test_decision_explanation_includes_semantic_penalties() -> None:
    finding = _semantic_finding()
    finding.semantic_risk = "medium"
    finding.semantic_evidence = {
        "shape_preserved": False,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }

    evaluate_findings(DecisionContext(findings=[finding], source="en"))
    explanation = finding._decision_explanation
    factor_codes = [factor["code"] for factor in explanation["score_factors"]]

    assert "meaning_loss_medium_penalty" in factor_codes
    assert "semantic_shape_mismatch_penalty" in factor_codes
    assert "meaning_loss_medium_penalty" in explanation["explanation_codes"]
    assert "semantic_shape_mismatch_penalty" in explanation["explanation_codes"]


def test_semantic_penalty_scoring_is_deterministic() -> None:
    finding_a = _semantic_finding()
    finding_b = _semantic_finding()
    for finding in (finding_a, finding_b):
        finding.semantic_risk = "medium"
        finding.semantic_evidence = {
            "shape_preserved": False,
            "action_preserved": False,
            "entity_alignment_ok": True,
        }

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en"))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en"))

    assert score_a == score_b
