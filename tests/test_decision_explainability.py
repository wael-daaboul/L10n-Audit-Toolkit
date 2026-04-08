from types import SimpleNamespace

from l10n_audit.core.context_profile import ContextProfile
from l10n_audit.core.decision_engine import DecisionContext, RouteAction, evaluate_findings
from l10n_audit.core.languagetool_layer import LTFinding


def test_calibration_transition_trace_is_captured() -> None:
    finding = LTFinding(
        key="k1",
        rule_id="R1",
        issue_category="complex",
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=True,
    )
    runtime = SimpleNamespace(
        config={"calibration": {"enabled": True, "mode": "enforce", "max_adjustment_per_run": 0.05}},
        metadata={
            "feedback_metrics": {
                "acceptance_rate_by_route": {"auto_fix": 0.7},
                "rejection_rate_by_route": {"auto_fix": 0.2},
            }
        },
        context_profile=ContextProfile(project_id="p1", domain="app"),
    )

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"), runtime=runtime)

    assert result.ai_review == [finding]
    explanation = finding._decision_explanation
    assert explanation["route_before_calibration"] == RouteAction.AUTO_FIX
    assert explanation["route_after_calibration"] == RouteAction.AI_REVIEW
    assert explanation["route_after_context"] == RouteAction.AI_REVIEW
    assert "calibration_downgrade" in explanation["explanation_codes"]
    assert runtime.metadata["context_routing_metrics"]["calibration_route_changes"] == 1
    assert runtime.metadata["context_routing_metrics"]["decision_explanations_emitted"] == 1


def test_context_transition_trace_is_captured() -> None:
    finding = LTFinding(
        key="k1",
        rule_id="R1",
        issue_category="style",
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=True,
    )
    runtime = SimpleNamespace(
        config={},
        metadata={},
        context_profile=ContextProfile(project_id="p1", domain="app", risk_tolerance="low"),
    )

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"), runtime=runtime)

    assert result.ai_review == [finding]
    explanation = finding._decision_explanation
    assert explanation["route_before_calibration"] == RouteAction.AUTO_FIX
    assert explanation["route_after_calibration"] == RouteAction.AUTO_FIX
    assert explanation["route_after_context"] == RouteAction.AI_REVIEW
    assert "risk_downgrade" in explanation["explanation_codes"]
    assert runtime.metadata["context_routing_metrics"]["context_route_changes"] == 1


def test_decision_explanation_is_deterministic() -> None:
    runtime = SimpleNamespace(
        config={},
        metadata={},
        context_profile=ContextProfile(project_id="p1", domain="app", risk_tolerance="low", style_strictness=0.2),
    )

    def build_finding() -> LTFinding:
        return LTFinding(
            key="k1",
            rule_id="R1",
            issue_category="style",
            message="m",
            original_text="o",
            suggested_text="fixed",
            offset=0,
            error_length=1,
            is_simple_fix=True,
        )

    finding_a = build_finding()
    finding_b = build_finding()

    evaluate_findings(DecisionContext(findings=[finding_a], source="en"), runtime=runtime)
    evaluate_findings(DecisionContext(findings=[finding_b], source="en"), runtime=runtime)

    assert finding_a._decision_explanation == finding_b._decision_explanation


def test_semantic_penalties_are_visible_in_decision_explanation() -> None:
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
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": False,
        "action_preserved": False,
        "entity_alignment_ok": False,
    }

    evaluate_findings(DecisionContext(findings=[finding], source="en"))
    explanation = finding._decision_explanation

    assert "meaning_loss_high_penalty" in explanation["explanation_codes"]
    assert "semantic_shape_mismatch_penalty" in explanation["explanation_codes"]
    assert "semantic_action_loss_penalty" in explanation["explanation_codes"]
    assert "semantic_entity_mismatch_penalty" in explanation["explanation_codes"]
    assert "semantic_evidence" in explanation["evidence_sources"]
    semantic_summary = next(item for item in explanation["contribution_summary"] if item["source"] == "semantic_evidence")
    assert "meaning_loss_high_penalty" in semantic_summary["codes"]
    assert semantic_summary["kinds"] == ["penalty"]


def test_extended_evidence_sources_are_visible_in_decision_explanation() -> None:
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
    finding.placeholder_integrity = "mismatch"
    finding.glossary_alignment = "approved"
    finding.structural_consistency = "shape_mismatch"

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"))
    explanation = finding._decision_explanation

    assert result.auto_fix == [finding]
    assert "placeholder_integrity" in explanation["evidence_sources"]
    assert "glossary_signal" in explanation["evidence_sources"]
    assert "structural_consistency" in explanation["evidence_sources"]
    assert any(item["source"] == "placeholder_integrity" for item in explanation["contribution_summary"])
    assert any(item["source"] == "glossary_signal" for item in explanation["contribution_summary"])
    assert any(item["source"] == "structural_consistency" for item in explanation["contribution_summary"])


def test_context_profile_weighting_is_visible_in_decision_explanation() -> None:
    finding = LTFinding(
        key="k1",
        rule_id="R1",
        issue_category="style",
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=False,
    )
    runtime = SimpleNamespace(
        config={},
        metadata={},
        context_profile=ContextProfile(
            project_id="p1",
            domain="app",
            risk_tolerance="low",
            style_strictness=0.4,
        ),
    )

    evaluate_findings(DecisionContext(findings=[finding], source="en"), runtime=runtime)
    explanation = finding._decision_explanation

    assert "context_profile_weighting" in explanation["evidence_sources"]
    assert explanation["context_profile_signals"]
    assert any(item["source"] == "context_profile_weighting" for item in explanation["contribution_summary"])
