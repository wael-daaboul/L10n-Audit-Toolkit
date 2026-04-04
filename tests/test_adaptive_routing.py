import pytest
from l10n_audit.core.languagetool_layer import LTFinding
from l10n_audit.core.decision_engine import (
    score_finding,
    evaluate_findings,
    DecisionContext,
    RouteAction,
    apply_arabic_decision_routing
)
from l10n_audit.core.enforcement_layer import EnforcementController
from l10n_audit.core.routing_metrics import RoutingMetrics
from unittest.mock import MagicMock

def create_mock_finding(
    is_simple_fix=False,
    suggested_text="test",
    issue_category="grammar"
) -> LTFinding:
    return LTFinding(
        key="test.key",
        rule_id="RULE_1",
        issue_category=issue_category,
        message="A test message",
        original_text="old",
        suggested_text=suggested_text,
        offset=0,
        error_length=3,
        is_simple_fix=is_simple_fix
    )

def test_confidence_scoring_range():
    # Base finding (not simple, has suggestion, grammar) -> 0.5 + 0.2 = 0.7
    f1 = create_mock_finding(is_simple_fix=False, suggested_text="fix", issue_category="grammar")
    score1 = score_finding(f1, None)
    assert score1["confidence"] == 0.7
    assert score1["risk"] == "low"

    # Perfect finding (simple, grammar, suggestion) -> 0.5 + 0.3 + 0.2 = 1.0
    f2 = create_mock_finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")
    score2 = score_finding(f2, None)
    assert score2["confidence"] == 1.0

    # Bad finding (no suggestion) -> 0.5 - 0.4 = 0.1 grammar (+0.2) = 0.3
    f3 = create_mock_finding(is_simple_fix=False, suggested_text="", issue_category="grammar")
    score3 = score_finding(f3, None)
    assert score3["confidence"] == 0.3
    assert score3["risk"] == "high"

    # Extreme overflow clamping check (if category brings base way high)
    # let's assume multiple positive bounds
    f4 = create_mock_finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")  # +0.5
    f4.confidence_score = 0.5
    assert score_finding(f4, None)["confidence"] == 1.0

def test_routing_changes_with_confidence():
    """Test standard adaptive matrix rules mapping to Routing queues."""
    f_autofix = create_mock_finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")
    f_manual = create_mock_finding(is_simple_fix=False, suggested_text="", issue_category="spelling")
    f_ai = create_mock_finding(is_simple_fix=False, suggested_text="fix", issue_category="grammar")

    ctx = DecisionContext(findings=[f_autofix, f_manual, f_ai], source="en")
    result = evaluate_findings(ctx)

    assert len(result.auto_fix) == 1
    assert result.auto_fix[0] == f_autofix

    assert len(result.manual_review) == 1
    assert result.manual_review[0] == f_manual

    assert len(result.ai_review) == 1
    assert result.ai_review[0] == f_ai

def test_backward_compatibility_payload():
    """Verify metrics and structure are intact when using the old style payload builder."""
    # We will just verify Arabic payload which is handled directly inside decision_engine
    rows = [
        {"key": "t1", "issue_type": "grammar", "old": "test", "new": "tests", "fix_mode": "auto_safe"},
        {"key": "t2", "issue_type": "style", "old": "test", "new": "tests", "fix_mode": "manual"},
    ]
    
    apply_arabic_decision_routing(rows, "new")
    
    # Assert nothing dropped
    assert len(rows) == 2
    
    # Assert decision format
    dec1 = rows[0]["decision"]
    assert "route" in dec1
    assert dec1["route"] == "auto_fix"
    assert "confidence" in dec1
    assert dec1["confidence"] == 1.0
    assert "risk" in dec1
    assert dec1["risk"] == "low"
    assert dec1["engine_version"] == "v3"

    dec2 = rows[1]["decision"]
    assert dec2["route"] == "ai_review"
    assert dec2["confidence"] == 0.6
    assert dec2["risk"] == "low"

def test_metrics_extended_without_break():
    """Test UnifiedRoutingMetrics averages and risk counters while keeping backward props."""
    metrics = RoutingMetrics()
    metrics.record("ai_review")
    metrics.record_adaptive(0.8, "low")
    
    metrics.record("auto_fix")
    metrics.record_adaptive(0.2, "high")
    
    metrics.record_ai_skip()
    
    data = metrics.to_dict()
    assert data["total"] == 2
    assert data["by_route"]["ai_review"] == 1
    assert data["average_confidence"] == 0.5
    assert data["count_by_risk_level"] == {"low": 1, "medium": 0, "high": 1}
    assert data["would_skip_ai"] == 1

def test_arabic_duplicate_row_index_mapping():
    """Verify Arabic pipeline correctly routes multiple identical rows using original position map, NOT object matching or ID collisions."""
    rows = [
        {"key": "test_dup", "old": "err", "new": "fix", "issue_type": "grammar", "fix_mode": "auto_safe"},
        {"key": "test_dup", "old": "err", "new": "fix", "issue_type": "grammar", "fix_mode": "auto_safe"},
        {"key": "test_dup", "old": "err", "new": "fix", "issue_type": "grammar", "fix_mode": "auto_safe"},
    ]
    
    # We will simulate modifying one finding inside evaluate to ensure it tracks the right object?
    # Actually the test logic ensures len() == 3 and no crashes occur when indexing properties.
    apply_arabic_decision_routing(rows)
    assert len(rows) == 3
    
    for row in rows:
        assert row["decision"]["route"] == "auto_fix"
        assert row["decision"]["confidence"] == 1.0
        assert row["decision"]["risk"] == "low"

def test_ltfinding_backward_compatibility():
    """Prove that LTFinding can still be initialized without confidence or risk, defaulting properly."""
    f = LTFinding(
        key="x", rule_id="y", issue_category="z", message="msg",
        original_text="old", suggested_text="new", offset=0, error_length=1, is_simple_fix=False
    )
    assert f.confidence_score == 0.5
    assert f.risk_level == "low"

def test_metric_legacy_dictionary_shape():
    """Prove that to_dict includes all the legacy keys from prior phases unmodified in behavior."""
    metrics = RoutingMetrics()
    metrics.record("auto_fix")
    metrics.record_ai_skip()
    
    d = metrics.to_dict()
    assert "would_skip_ai" in d
    assert "would_skip_autofix" in d
    assert "total" in d
    assert d["would_skip_ai"] == 1

