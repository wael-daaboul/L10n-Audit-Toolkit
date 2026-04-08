from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings
from l10n_audit.core.decision_quality_harness import evaluate_decision_quality
from l10n_audit.core.languagetool_layer import LTFinding
from l10n_audit.core.routing_metrics import enrich_with_decision_quality


def _finding(
    key: str,
    category: str,
    suggested_text: str,
    simple: bool,
) -> LTFinding:
    return LTFinding(
        key=key,
        rule_id=f"R-{key}",
        issue_category=category,
        message="m",
        original_text="o",
        suggested_text=suggested_text,
        offset=0,
        error_length=1,
        is_simple_fix=simple,
    )


def test_route_distribution_and_confidence_bands_are_correct() -> None:
    auto = _finding("auto", "grammar", "fixed", True)
    ai = _finding("ai", "style", "fixed", False)
    manual = _finding("manual", "complex", "", False)
    evaluate_findings(DecisionContext(findings=[auto, ai, manual], source="en"))

    summary = evaluate_decision_quality([auto, ai, manual])

    assert summary["route_distribution"] == {
        "auto_fix": 1,
        "ai_review": 1,
        "manual_review": 1,
        "dropped": 0,
        "unknown": 0,
    }
    assert summary["confidence_bands"] == {
        "high_confidence": 1,
        "medium_confidence": 1,
        "low_confidence": 1,
    }


def test_evidence_source_usage_is_counted_correctly() -> None:
    semantic = _finding("semantic", "grammar", "fixed", True)
    semantic.semantic_risk = "high"
    semantic.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    profile = _finding("profile", "style", "fixed", False)

    evaluate_findings(
        DecisionContext(
            findings=[semantic, profile],
            source="en",
            metadata={
                "context_profile": {"risk_tolerance": "low", "style_strictness": 0.4},
            },
        )
    )

    summary = evaluate_decision_quality([semantic, profile])

    assert summary["evidence_source_usage"]["semantic_evidence"] == 1
    assert summary["evidence_source_usage"]["context_profile_weighting"] >= 1
    assert summary["evidence_source_usage"]["category_signal"] == 2


def test_contribution_impact_summary_is_correct() -> None:
    finding = _finding("k1", "grammar", "fixed", True)
    finding.semantic_risk = "high"
    finding.semantic_evidence = {
        "shape_preserved": False,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    evaluate_findings(DecisionContext(findings=[finding], source="en"))

    summary = evaluate_decision_quality([finding])
    semantic_summary = summary["contribution_impact_summary"]["semantic_evidence"]
    category_summary = summary["contribution_impact_summary"]["category_signal"]

    assert semantic_summary["source_count"] == 2
    assert semantic_summary["penalty_count"] == 2
    assert semantic_summary["bonus_count"] == 0
    assert semantic_summary["source_total_delta"] == -0.4
    assert category_summary["bonus_count"] == 1
    assert category_summary["source_total_delta"] == 0.2


def test_anomaly_detection_and_missing_explanation_work() -> None:
    auto = _finding("auto", "grammar", "fixed", True)
    evaluate_findings(DecisionContext(findings=[auto], source="en"))
    auto.confidence_score = 0.79

    manual = _finding("manual", "complex", "", False)
    evaluate_findings(DecisionContext(findings=[manual], source="en"))
    manual.confidence_score = 0.31

    missing = _finding("missing", "style", "fixed", False)
    missing.confidence_score = 0.5

    summary = evaluate_decision_quality([auto, manual, missing])
    indicators = summary["quality_risk_indicators"]

    assert indicators["low_confidence_auto_fix_count"] == 1
    assert indicators["high_confidence_manual_review_count"] == 1
    assert indicators["missing_explanation_count"] == 1


def test_harness_output_is_deterministic() -> None:
    first = _finding("first", "grammar", "fixed", True)
    first.glossary_alignment = "violation"
    second = _finding("second", "style", "fixed", False)
    metadata = {"context_profile": {"risk_tolerance": "low", "style_strictness": 0.4}}

    evaluate_findings(DecisionContext(findings=[first, second], source="en", metadata=metadata))
    summary_a = evaluate_decision_quality([first, second])
    summary_b = evaluate_decision_quality([first, second])

    assert summary_a == summary_b


def test_routing_metrics_enrichment_is_additive() -> None:
    metrics = {"total": 2, "by_route": {"auto_fix": 1, "ai_review": 1}}
    quality = {"route_distribution": {"auto_fix": 1, "ai_review": 1, "manual_review": 0, "dropped": 0, "unknown": 0}}

    enriched = enrich_with_decision_quality(metrics, quality)

    assert enriched["total"] == 2
    assert enriched["by_route"] == {"auto_fix": 1, "ai_review": 1}
    assert enriched["decision_quality"] == quality


def test_decision_quality_contract_is_respected() -> None:
    auto = _finding("auto", "grammar", "fixed", True)
    ai = _finding("ai", "style", "fixed", False)
    evaluate_findings(DecisionContext(findings=[auto, ai], source="en"))

    summary = evaluate_decision_quality([auto, ai])

    assert "route_distribution" in summary
    assert "confidence_bands" in summary
    assert "evidence_source_usage" in summary
    assert "contribution_impact_summary" in summary
    assert "quality_risk_indicators" in summary
