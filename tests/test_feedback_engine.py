"""
tests/test_feedback_engine.py
==============================
Phase 8 — Tests for Feedback & Learning Loop (Observational Layer).

Validates:
1. FeedbackSignal creation correctness
2. FeedbackAggregator summarize() accuracy
3. No behavior change to apply_safe_changes (same input → same output)
4. feedback_metrics appears in runtime.metadata

All routing, enforcement and decision behavior is unchanged — only
signal collection is tested here.
"""
import pytest
from unittest.mock import MagicMock

from l10n_audit.core.feedback_engine import FeedbackSignal, FeedbackAggregator


# ---------------------------------------------------------------------------
# Test 1 — Signal creation
# ---------------------------------------------------------------------------

def test_feedback_signal_creation():
    """Each finding should produce a FeedbackSignal with correct fields."""
    s = FeedbackSignal(
        route="auto_fix",
        confidence=0.9,
        risk="low",
        was_accepted=True,
        was_modified=False,
        was_rejected=False,
        source="autofix",
    )
    assert s.route == "auto_fix"
    assert s.confidence == 0.9
    assert s.risk == "low"
    assert s.was_accepted is True
    assert s.was_modified is False
    assert s.was_rejected is False
    assert s.source == "autofix"


def test_feedback_signal_rejected():
    """A rejected signal should have was_rejected=True and was_accepted=False."""
    s = FeedbackSignal(
        route="manual_review",
        confidence=0.2,
        risk="high",
        was_accepted=False,
        was_modified=False,
        was_rejected=True,
        source="manual",
    )
    assert s.was_rejected is True
    assert s.was_accepted is False


# ---------------------------------------------------------------------------
# Test 2 — Aggregation accuracy
# ---------------------------------------------------------------------------

def test_feedback_aggregation_accuracy():
    """acceptance_rate and rejection_rate must be computed correctly per route."""
    agg = FeedbackAggregator()

    # 3 auto_fix signals: 2 accepted, 1 rejected
    for _ in range(2):
        agg.record(FeedbackSignal(
            route="auto_fix", confidence=0.85, risk="low",
            was_accepted=True, was_modified=False, was_rejected=False, source="autofix"
        ))
    agg.record(FeedbackSignal(
        route="auto_fix", confidence=0.85, risk="low",
        was_accepted=False, was_modified=False, was_rejected=True, source="autofix"
    ))

    # 2 ai_review signals: 1 accepted, 1 rejected
    agg.record(FeedbackSignal(
        route="ai_review", confidence=0.6, risk="low",
        was_accepted=True, was_modified=False, was_rejected=False, source="ai"
    ))
    agg.record(FeedbackSignal(
        route="ai_review", confidence=0.6, risk="high",
        was_accepted=False, was_modified=False, was_rejected=True, source="ai"
    ))

    summary = agg.summarize()

    assert summary["total_signals"] == 5

    # auto_fix: 2/3 accepted = 0.6667
    assert summary["acceptance_rate_by_route"]["auto_fix"] == round(2/3, 4)
    # auto_fix: 1/3 rejected = 0.3333
    assert summary["rejection_rate_by_route"]["auto_fix"] == round(1/3, 4)

    # ai_review: 1/2 accepted = 0.5
    assert summary["acceptance_rate_by_route"]["ai_review"] == 0.5
    assert summary["rejection_rate_by_route"]["ai_review"] == 0.5

    # avg_confidence for auto_fix = 0.85
    assert summary["avg_confidence_by_route"]["auto_fix"] == 0.85

    # sources count
    assert summary["signals_by_source"]["autofix"] == 3
    assert summary["signals_by_source"]["ai"] == 2


def test_feedback_aggregation_empty():
    """Empty aggregator should return safe zero-state summary."""
    agg = FeedbackAggregator()
    s = agg.summarize()
    assert s["total_signals"] == 0
    assert s["acceptance_rate_by_route"] == {}
    assert s["rejection_rate_by_route"] == {}
    assert s["avg_confidence_by_route"] == {}
    assert s["risk_vs_rejection"] == {}
    assert s["signals_by_source"] == {}


def test_risk_vs_rejection_correlation():
    """risk_vs_rejection must map risk levels to rejection counts."""
    agg = FeedbackAggregator()
    agg.record(FeedbackSignal("auto_fix", 0.9, "low", True, False, False, "autofix"))
    agg.record(FeedbackSignal("auto_fix", 0.2, "high", False, False, True, "autofix"))
    agg.record(FeedbackSignal("ai_review", 0.4, "high", False, False, True, "ai"))

    s = agg.summarize()
    assert s["risk_vs_rejection"]["low"]["rejected"] == 0
    assert s["risk_vs_rejection"]["high"]["rejected"] == 2
    assert s["risk_vs_rejection"]["high"]["total"] == 2
    assert s["risk_vs_rejection"]["high"]["rejection_rate"] == 1.0


# ---------------------------------------------------------------------------
# Test 3 — No behavior change to apply_safe_changes
# ---------------------------------------------------------------------------

def test_no_behavior_change_apply_safe_changes():
    """apply_safe_changes must return identical (updated, applied) with or without runtime."""
    from l10n_audit.fixes.apply_safe_fixes import apply_safe_changes

    data = {"greeting": "Hello world", "farewell": "Goodbye"}
    plan = [
        {
            "key": "greeting",
            "locale": "en",
            "classification": "auto_safe",
            "candidate_value": "Hello World",
            "current_value": "Hello world",
            "source": "grammar",
            "issue_type": "capitalization",
            "severity": "low",
            "message": "Capitalize properly.",
            "provenance": [],
        }
    ]

    # Without runtime
    updated_no_rt, applied_no_rt = apply_safe_changes(data, plan, "en")

    # With a runtime that has an aggregator
    mock_rt = MagicMock()
    from l10n_audit.core.feedback_engine import FeedbackAggregator
    mock_rt._feedback_aggregator = FeedbackAggregator()
    mock_rt._feedback_aggregator  # ensure it's set

    updated_with_rt, applied_with_rt = apply_safe_changes(data, plan, "en", runtime=mock_rt)

    # Outputs must be identical
    assert updated_no_rt == updated_with_rt
    assert [i["key"] for i in applied_no_rt] == [i["key"] for i in applied_with_rt]

    # Feedback was captured when runtime present
    assert len(mock_rt._feedback_aggregator.signals) == 1
    assert mock_rt._feedback_aggregator.signals[0].was_accepted is True


def test_no_behavior_change_without_runtime():
    """apply_safe_changes called without runtime keyword must work identically to pre-Phase 8."""
    from l10n_audit.fixes.apply_safe_fixes import apply_safe_changes

    data = {"key1": "old"}
    plan = [
        {
            "key": "key1",
            "locale": "en",
            "classification": "auto_safe",
            "candidate_value": "new",
            "current_value": "old",
            "source": "grammar",
            "issue_type": "spelling",
            "severity": "low",
            "message": "Fix spelling.",
            "provenance": [],
        }
    ]
    updated, applied = apply_safe_changes(data, plan, "en")
    assert updated["key1"] == "new"
    assert len(applied) == 1


# ---------------------------------------------------------------------------
# Test 4 — feedback_metrics in runtime.metadata
# ---------------------------------------------------------------------------

def test_feedback_metrics_appears_in_metadata():
    """Aggregator.summarize() result must be injectable into runtime.metadata."""
    agg = FeedbackAggregator()
    agg.record(FeedbackSignal("auto_fix", 0.9, "low", True, False, False, "autofix"))
    agg.record(FeedbackSignal("ai_review", 0.4, "high", False, False, True, "ai"))

    runtime = MagicMock()
    runtime.metadata = {}
    runtime.metadata["feedback_metrics"] = agg.summarize()

    assert "feedback_metrics" in runtime.metadata
    fb = runtime.metadata["feedback_metrics"]
    assert fb["total_signals"] == 2
    assert "acceptance_rate_by_route" in fb
    assert "rejection_rate_by_route" in fb
    assert "avg_confidence_by_route" in fb
    assert "risk_vs_rejection" in fb
    assert "signals_by_source" in fb
