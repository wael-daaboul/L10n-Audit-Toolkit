import pytest

from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings, score_finding
from l10n_audit.core.languagetool_layer import LTFinding


def _build_finding(category: str = "grammar") -> LTFinding:
    return LTFinding(
        key="k1",
        rule_id="R1",
        issue_category=category,
        message="m",
        original_text="o",
        suggested_text="fixed",
        offset=0,
        error_length=1,
        is_simple_fix=True,
    )


def test_contribution_model_is_structured_and_deterministic() -> None:
    finding_a = _build_finding()
    finding_b = _build_finding()

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en"))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en"))

    assert score_a == score_b
    assert score_a["score_factors"] == [
        {"code": "simple_fix_bonus", "delta": 0.3, "kind": "bonus", "source": "base_rule"},
        {"code": "grammar_signal", "delta": 0.2, "kind": "bonus", "source": "category_signal"},
    ]
    assert score_a["contribution_summary"] == [
        {"source": "base_rule", "total_delta": 0.3, "codes": ["simple_fix_bonus"], "kinds": ["bonus"]},
        {"source": "category_signal", "total_delta": 0.2, "codes": ["grammar_signal"], "kinds": ["bonus"]},
    ]


def test_legacy_finding_route_parity_is_preserved() -> None:
    finding = _build_finding(category="grammar")

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"))

    assert result.auto_fix == [finding]
    assert result.ai_review == []
    assert result.manual_review == []
    assert finding.confidence_score == pytest.approx(1.0)


def test_semantic_evidence_is_a_first_class_contribution_source() -> None:
    finding = _build_finding()
    finding.semantic_risk = "medium"
    finding.semantic_evidence = {
        "shape_preserved": False,
        "action_preserved": True,
        "entity_alignment_ok": True,
    }

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    semantic_factors = [factor for factor in score["score_factors"] if factor["source"] == "semantic_evidence"]
    assert [factor["code"] for factor in semantic_factors] == [
        "meaning_loss_medium_penalty",
        "semantic_shape_mismatch_penalty",
    ]
    semantic_summary = next(item for item in score["contribution_summary"] if item["source"] == "semantic_evidence")
    assert semantic_summary["total_delta"] == pytest.approx(-0.25)
    assert semantic_summary["kinds"] == ["penalty"]


def test_placeholder_evidence_appears_explicitly() -> None:
    finding = _build_finding()
    finding.placeholder_integrity = "missing"

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    placeholder_factor = next(
        factor for factor in score["score_factors"] if factor["code"] == "placeholder_missing_penalty"
    )
    assert placeholder_factor["source"] == "placeholder_integrity"
    assert placeholder_factor["kind"] == "penalty"
    assert score["confidence"] == pytest.approx(0.8)


def test_glossary_evidence_appears_explicitly() -> None:
    finding = _build_finding()
    finding.glossary_alignment = "violation"

    score = score_finding(finding, DecisionContext(findings=[finding], source="en"))

    glossary_factor = next(
        factor for factor in score["score_factors"] if factor["code"] == "glossary_violation_penalty"
    )
    assert glossary_factor["source"] == "glossary_signal"
    assert glossary_factor["kind"] == "penalty"

    aligned_finding = _build_finding()
    aligned_finding.glossary_alignment = "approved"
    aligned_score = score_finding(aligned_finding, DecisionContext(findings=[aligned_finding], source="en"))
    assert "glossary_alignment_bonus" in [factor["code"] for factor in aligned_score["score_factors"]]


def test_structural_evidence_can_be_read_from_ctx_metadata() -> None:
    finding = _build_finding()
    ctx = DecisionContext(
        findings=[finding],
        source="en",
        metadata={"structural_consistency_by_key": {"k1": "nested_collision"}},
    )

    score = score_finding(finding, ctx)

    structural_factor = next(
        factor for factor in score["score_factors"] if factor["code"] == "structural_collision_penalty"
    )
    assert structural_factor["source"] == "structural_consistency"
    structural_summary = next(
        item for item in score["contribution_summary"] if item["source"] == "structural_consistency"
    )
    assert structural_summary["codes"] == ["structural_collision_penalty"]
