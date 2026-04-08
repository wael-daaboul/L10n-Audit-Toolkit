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


def test_no_profile_means_no_profile_weighting() -> None:
    finding = _build_finding(category="style", simple=False)

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    assert "context_profile_weighting" not in score["evidence_sources"]
    assert score["context_profile_signals"] == []


def test_low_risk_tolerance_penalty_appears_explicitly() -> None:
    finding = _build_finding(category="style", simple=False)
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={"context_profile": {"risk_tolerance": "low"}},
    )

    score = score_finding(finding, ctx)

    factor = next(
        item for item in score["score_factors"] if item["code"] == "profile_low_risk_tolerance_penalty"
    )
    assert factor["source"] == "context_profile_weighting"
    assert factor["delta"] == pytest.approx(-0.03)


def test_style_strictness_affects_style_family_only() -> None:
    style_finding = _build_finding(category="style", simple=False)
    grammar_finding = _build_finding(category="grammar", simple=False)
    metadata = {"context_profile": {"style_strictness": 0.6}}

    style_score = score_finding(style_finding, DecisionContext(findings=[style_finding], source="en", metadata=metadata))
    grammar_score = score_finding(grammar_finding, DecisionContext(findings=[grammar_finding], source="en", metadata=metadata))

    assert "profile_style_strictness_penalty" in style_score["explanation_codes"]
    assert "profile_style_strictness_penalty" not in grammar_score["explanation_codes"]


def test_glossary_enforced_caution_appears_explicitly() -> None:
    finding = _build_finding()
    finding.glossary_alignment = "violation"
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={"context_profile": {"glossary_enforced": True}},
    )

    score = score_finding(finding, ctx)

    assert "profile_glossary_enforced_caution" in score["explanation_codes"]


def test_prefer_manual_review_does_not_hard_override_route() -> None:
    finding = _build_finding(category="style", simple=False)
    finding.semantic_risk = "medium"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={"context_profile": {"prefer_manual_review": True}},
    )

    result = evaluate_findings(ctx)

    assert result.ai_review == [finding]
    assert result.auto_fix == []
    assert result.manual_review == []
    assert finding.confidence_score == pytest.approx(0.43)


def test_profile_weighting_is_deterministic() -> None:
    metadata = {
        "context_profile": {
            "risk_tolerance": "low",
            "style_strictness": 0.4,
            "glossary_enforced": True,
            "prefer_manual_review": True,
        }
    }
    finding_a = _build_finding(category="style", simple=False)
    finding_b = _build_finding(category="style", simple=False)
    for finding in (finding_a, finding_b):
        finding.glossary_alignment = "drift"

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en", metadata=metadata))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en", metadata=metadata))

    assert score_a == score_b


def test_context_profile_contribution_is_bounded() -> None:
    finding = _build_finding(category="style", simple=False)
    finding.glossary_alignment = "violation"
    finding.semantic_risk = "medium"
    finding.semantic_evidence = {
        "shape_preserved": True,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={
            "context_profile": {
                "risk_tolerance": "low",
                "style_strictness": 1.0,
                "glossary_enforced": True,
                "prefer_manual_review": True,
            }
        },
    )

    score = score_finding(finding, ctx)
    profile_total = sum(
        entry["delta"]
        for entry in score["context_profile_signals"]
    )

    assert abs(profile_total) <= 0.08
    assert profile_total == pytest.approx(-0.06)
