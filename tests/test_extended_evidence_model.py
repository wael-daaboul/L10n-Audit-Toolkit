from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings, score_finding
from l10n_audit.core.languagetool_layer import LTFinding


def _build_finding() -> LTFinding:
    return LTFinding(
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


def test_legacy_parity_without_extended_evidence() -> None:
    finding = _build_finding()

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"))

    assert result.auto_fix == [finding]
    assert result.ai_review == []
    assert result.manual_review == []
    assert finding.confidence_score == 1.0


def test_no_hard_route_shortcut_for_extended_evidence() -> None:
    finding = _build_finding()
    finding.placeholder_integrity = "missing"
    finding.glossary_alignment = "violation"

    result = evaluate_findings(DecisionContext(findings=[finding], source="en"))

    assert result.ai_review == [finding]
    assert result.auto_fix == []
    assert result.manual_review == []
    assert finding.confidence_score == 0.65


def test_extended_evidence_scoring_is_deterministic() -> None:
    finding_a = _build_finding()
    finding_b = _build_finding()
    for finding in (finding_a, finding_b):
        finding.placeholder_integrity = "mismatch"
        finding.glossary_alignment = "approved"
        finding.structural_consistency = "nested_collision"

    score_a = score_finding(finding_a, DecisionContext(findings=[finding_a], source="en"))
    score_b = score_finding(finding_b, DecisionContext(findings=[finding_b], source="en"))

    assert score_a == score_b
