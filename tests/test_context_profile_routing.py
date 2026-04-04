"""
tests/test_context_profile_routing.py
=======================================
Phase 12 — Cross-Project Intelligence Layer Tests.

Contract under test:
- No profile → zero behavior change (full backward compatibility)
- Context rules are deterministic pure functions
- Rules fire AFTER scoring and calibration, before queue commit
- Arabic pipeline: context may attach metadata but MUST NOT alter row count/order
- Metrics (context_adjusted_count, context_downgrade_count, context_override_manual_count)
  are correctly incremented
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from l10n_audit.core.context_profile import (
    ContextProfile,
    ContextAdjustment,
    apply_context_rules,
    get_context_profile,
)
from l10n_audit.core.decision_engine import (
    DecisionContext,
    DecisionResult,
    RouteAction,
    evaluate_findings,
    score_finding,
)
from l10n_audit.core.languagetool_layer import LTFinding
from l10n_audit.core.routing_metrics import RoutingMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _Runtime:
    config: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    context_profile: Any = None


def _finding(
    is_simple_fix: bool = True,
    suggested_text: str = "fix",
    issue_category: str = "grammar",
) -> LTFinding:
    f = LTFinding(
        key="test_key",
        rule_id="RULE_X",
        issue_category=issue_category,
        message="test message",
        original_text="original",
        suggested_text=suggested_text,
        offset=0,
        error_length=4,
        is_simple_fix=is_simple_fix,
    )
    f.confidence_score = 0.0
    f.risk_level = "low"
    return f


def _ctx(*findings) -> DecisionContext:
    return DecisionContext(findings=list(findings), source="en")


def _profile(**kwargs) -> ContextProfile:
    defaults = dict(project_id="test_proj", domain="test")
    defaults.update(kwargs)
    return ContextProfile(**defaults)


def _route_of(result: DecisionResult, finding: LTFinding) -> str:
    for f in result.auto_fix:
        if f is finding:
            return "auto_fix"
    for f in result.ai_review:
        if f is finding:
            return "ai_review"
    for f in result.manual_review:
        if f is finding:
            return "manual_review"
    return "dropped"


# ---------------------------------------------------------------------------
# Test 1 — No Profile = No Behavior Change
# ---------------------------------------------------------------------------

def test_no_profile_identical_to_baseline():
    """No context_profile must produce identical results to explicit context_profile=None.

    Uses the SAME finding evaluated twice — once with no profile attached to runtime,
    once with explicit None. Asserts route, confidence, risk, queue placement, and
    absence of context keys are identical in both cases.
    """
    def _run(rt):
        f = _finding(is_simple_fix=True, suggested_text="corrected", issue_category="grammar")
        result = evaluate_findings(_ctx(f), rt)
        route = _route_of(result, f)
        return {
            "route": route,
            "confidence": round(f.confidence_score, 2),
            "risk": f.risk_level,
            "in_auto_fix": f in result.auto_fix,
            "in_ai_review": f in result.ai_review,
            "in_manual_review": f in result.manual_review,
            "context_adjustment_is_none": f._context_adjustment is None,
            "context_routing_metrics_absent": "context_routing_metrics" not in rt.metadata,
        }

    # Runtime with no context_profile attribute at all
    rt_absent = _Runtime()
    del rt_absent.context_profile  # ensure the attribute is truly absent

    # Runtime with explicit context_profile=None
    rt_explicit_none = _Runtime(context_profile=None)

    result_absent = _run(rt_absent)
    result_explicit_none = _run(rt_explicit_none)

    assert result_absent == result_explicit_none, (
        f"No-profile outputs diverged:\n  absent={result_absent}\n  explicit_none={result_explicit_none}"
    )
    # Confirm all the expected values
    assert result_absent["route"] == "auto_fix"            # grammar + simple_fix → AUTO_FIX
    assert result_absent["context_adjustment_is_none"] is True
    assert result_absent["context_routing_metrics_absent"] is True


# ---------------------------------------------------------------------------
# Test 2 — Risk Downgrade: AUTO_FIX → AI_REVIEW when risk_tolerance="low"
# ---------------------------------------------------------------------------

def test_risk_downgrade_auto_fix_to_ai_review():
    """A finding that would normally be AUTO_FIX must be downgraded to AI_REVIEW
    when the profile's risk_tolerance is 'low'."""
    # is_simple_fix=True + suggested_text present → base score >= 0.8 → AUTO_FIX
    f = _finding(is_simple_fix=True, suggested_text="corrected", issue_category="grammar")

    profile = _profile(risk_tolerance="low")
    rt = _Runtime(context_profile=profile)

    result = evaluate_findings(_ctx(f), rt)

    assert f in result.ai_review, "AUTO_FIX must downgrade to AI_REVIEW with risk_tolerance=low"
    assert f not in result.auto_fix

    adj: ContextAdjustment = f._context_adjustment
    assert adj is not None
    assert adj.context_applied is True
    assert "risk_downgrade" in adj.rules_triggered
    assert adj.route_before == "auto_fix"
    assert adj.route_after == "ai_review"

    # Metrics incremented
    metrics = rt.metadata["context_routing_metrics"]
    assert metrics["context_adjusted_count"] >= 1
    assert metrics["context_downgrade_count"] >= 1


def test_risk_downgrade_ai_review_to_manual_when_low_confidence():
    """AI_REVIEW → MANUAL_REVIEW when risk_tolerance=low AND confidence < 0.6."""
    # No suggested text → confidence -= 0.4 → 0.1 → MANUAL_REVIEW normally.
    # Use is_simple_fix=False, suggested_text="" to get low confidence,
    # but add a style category (+0.1) and no fix so confidence = 0.5 - 0.4 = 0.1 → MANUAL already.
    # Instead craft a case landing in AI_REVIEW range (0.3 < confidence < 0.8, not simple fix).
    f = _finding(is_simple_fix=False, suggested_text="something", issue_category="style")
    # Base: 0.5 + 0.1 (style) = 0.6 → AI_REVIEW (no simple fix → not AUTO_FIX)
    # With risk_tolerance=low: AI_REVIEW + confidence(0.6) >= 0.6 → stays AI_REVIEW
    # So test the < 0.6 threshold explicitly via apply_context_rules directly

    profile = _profile(risk_tolerance="low")

    # Craft finding with pre-set confidence below 0.6
    f2 = _finding(is_simple_fix=False, suggested_text="something", issue_category="grammar")
    f2.confidence_score = 0.55
    f2.risk_level = "low"

    final_route, adj = apply_context_rules(f2, RouteAction.AI_REVIEW, profile)

    assert final_route == RouteAction.MANUAL_REVIEW
    assert "risk_downgrade" in adj.rules_triggered


def test_risk_downgrade_ai_review_stays_when_high_confidence():
    """AI_REVIEW stays as AI_REVIEW when risk_tolerance=low but confidence >= 0.6."""
    profile = _profile(risk_tolerance="low")

    f = _finding(is_simple_fix=False, suggested_text="fix", issue_category="grammar")
    f.confidence_score = 0.65
    f.risk_level = "low"

    final_route, adj = apply_context_rules(f, RouteAction.AI_REVIEW, profile)

    assert final_route == RouteAction.AI_REVIEW
    # No downgrade for AI_REVIEW at confidence >= 0.6 even with risk_tolerance=low
    assert "risk_downgrade" not in adj.rules_triggered


# ---------------------------------------------------------------------------
# Test 3 — Style Strictness Reduces Confidence
# ---------------------------------------------------------------------------

def test_style_strictness_reduces_confidence():
    """style_strictness applies a numeric penalty to confidence for style findings."""
    profile = _profile(style_strictness=0.8)

    f = _finding(is_simple_fix=False, suggested_text="fix", issue_category="style")
    f.confidence_score = 0.7
    f.risk_level = "low"

    _, adj = apply_context_rules(f, RouteAction.AI_REVIEW, profile)

    expected_penalty = 0.8 * 0.3   # = 0.24
    expected_after = max(0.0, 0.7 - expected_penalty)  # = 0.46

    assert abs(adj.confidence_after - expected_after) < 1e-9
    assert adj.confidence_after < adj.confidence_before
    assert "style_penalty" in adj.rules_triggered


def test_style_strictness_zero_no_change():
    """style_strictness=0.0 must produce zero confidence change."""
    profile = _profile(style_strictness=0.0)

    f = _finding(is_simple_fix=False, suggested_text="fix", issue_category="style")
    f.confidence_score = 0.7
    f.risk_level = "low"

    _, adj = apply_context_rules(f, RouteAction.AI_REVIEW, profile)

    assert adj.confidence_before == adj.confidence_after
    assert "style_penalty" not in adj.rules_triggered


def test_style_strictness_does_not_apply_to_grammar():
    """style_strictness penalty must ONLY fire for issue_category='style'."""
    profile = _profile(style_strictness=1.0)

    f = _finding(is_simple_fix=False, suggested_text="fix", issue_category="grammar")
    f.confidence_score = 0.7
    f.risk_level = "low"

    _, adj = apply_context_rules(f, RouteAction.AI_REVIEW, profile)

    assert "style_penalty" not in adj.rules_triggered
    assert adj.confidence_before == adj.confidence_after


# ---------------------------------------------------------------------------
# Test 4 — Manual Preference Override
# ---------------------------------------------------------------------------

def test_manual_preference_overrides_high_risk():
    """prefer_manual_review=True forces MANUAL_REVIEW when risk_level='high'."""
    profile = _profile(prefer_manual_review=True)

    f = _finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")
    f.confidence_score = 0.9
    f.risk_level = "high"

    final_route, adj = apply_context_rules(f, RouteAction.AUTO_FIX, profile)

    assert final_route == RouteAction.MANUAL_REVIEW
    assert "manual_override" in adj.rules_triggered


def test_manual_preference_does_not_affect_low_risk():
    """prefer_manual_review=True must NOT override low-risk findings."""
    profile = _profile(prefer_manual_review=True)

    f = _finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")
    f.confidence_score = 0.9
    f.risk_level = "low"

    final_route, adj = apply_context_rules(f, RouteAction.AUTO_FIX, profile)

    # risk_level is "low" → manual_override must not fire
    assert "manual_override" not in adj.rules_triggered
    assert final_route == RouteAction.AUTO_FIX


# ---------------------------------------------------------------------------
# Test 5 — Determinism (3 independent runs produce identical output)
# ---------------------------------------------------------------------------

def test_determinism_three_runs():
    def run():
        profile = _profile(
            risk_tolerance="low",
            style_strictness=0.5,
            prefer_manual_review=True,
        )
        rt = _Runtime(context_profile=profile)

        findings = [
            _finding(is_simple_fix=True,  suggested_text="fix",  issue_category="grammar"),
            _finding(is_simple_fix=False, suggested_text="",     issue_category="style"),
            _finding(is_simple_fix=True,  suggested_text="edit", issue_category="style"),
        ]
        result = evaluate_findings(_ctx(*findings), rt)
        return (
            len(result.auto_fix),
            len(result.ai_review),
            len(result.manual_review),
            rt.metadata["context_routing_metrics"]["context_adjusted_count"],
        )

    a, b, c = run(), run(), run()
    assert a == b == c, f"Non-deterministic output: {a} vs {b} vs {c}"


# ---------------------------------------------------------------------------
# Test 6 — Arabic Isolation: context annotates but does NOT alter row count/order
# ---------------------------------------------------------------------------

def test_arabic_isolation_row_count_unchanged():
    """Arabic pipeline with a context_profile attached must preserve len(rows)."""
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing

    rows = [
        {"key": f"k{i}", "old": f"text_{i}", "new": "",
         "issue_type": "style", "message": "msg", "fix_mode": "review_required"}
        for i in range(5)
    ]
    input_count = len(rows)

    # apply_arabic_decision_routing does not receive runtime, so context is not applied
    # through that path. This test confirms the function preserves row count regardless.
    apply_arabic_decision_routing(rows, suggestion_key="new")

    assert len(rows) == input_count, "Arabic routing must not drop any rows"
    for row in rows:
        assert "decision" in row, "Every row must have a decision annotation"


def test_arabic_isolation_ordering_unchanged():
    """Arabic row order must be preserved exactly (index-based mapping)."""
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing

    rows = [
        {"key": f"key_{i}", "old": f"original_{i}", "new": "",
         "issue_type": "whitespace", "message": "spacing", "fix_mode": "auto_safe"}
        for i in range(8)
    ]
    apply_arabic_decision_routing(rows, suggestion_key="new")

    for expected_idx, row in enumerate(rows):
        assert row["key"] == f"key_{expected_idx}", (
            f"Row ordering violated at position {expected_idx}"
        )


# ---------------------------------------------------------------------------
# Test 7 — Metrics correctly incremented
# ---------------------------------------------------------------------------

def test_context_metrics_incremented():
    """context_adjusted_count must be > 0 when rules fire."""
    profile = _profile(risk_tolerance="low")
    rt = _Runtime(context_profile=profile)

    # AUTO_FIX-eligible finding → risk_downgrade fires
    findings = [
        _finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar"),
        _finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar"),
    ]
    evaluate_findings(_ctx(*findings), rt)

    metrics = rt.metadata["context_routing_metrics"]
    assert metrics["context_adjusted_count"] > 0
    assert metrics["context_downgrade_count"] > 0


def test_context_metrics_zero_when_no_profile():
    """context_routing_metrics must NOT appear in metadata when no profile is set."""
    rt = _Runtime(context_profile=None)
    findings = [_finding(is_simple_fix=True, suggested_text="fix")]
    evaluate_findings(_ctx(*findings), rt)

    assert "context_routing_metrics" not in rt.metadata


def test_context_override_manual_counter():
    """context_override_manual_count increments for manual_override rule."""
    profile = _profile(prefer_manual_review=True)
    rt = _Runtime(context_profile=profile)

    # suggested_text="" → risk="high" → manual_override fires
    findings = [_finding(is_simple_fix=True, suggested_text="", issue_category="grammar")]
    evaluate_findings(_ctx(*findings), rt)

    metrics = rt.metadata["context_routing_metrics"]
    assert metrics["context_override_manual_count"] >= 1


# ---------------------------------------------------------------------------
# Test 8 — Glossary Enforcement Annotation (no behavior change)
# ---------------------------------------------------------------------------

def test_glossary_enforcement_annotation_only():
    """glossary_enforced=True must annotate finding.requires_glossary_check=True
    without changing the route."""
    profile = _profile(glossary_enforced=True)

    f = _finding(is_simple_fix=True, suggested_text="fix", issue_category="grammar")
    f.confidence_score = 0.5
    f.risk_level = "low"

    final_route, adj = apply_context_rules(f, RouteAction.AI_REVIEW, profile)

    assert final_route == RouteAction.AI_REVIEW  # no route change
    assert getattr(f, "requires_glossary_check", False) is True
    assert "style_penalty" not in adj.rules_triggered
    assert "risk_downgrade" not in adj.rules_triggered


# ---------------------------------------------------------------------------
# Test 9 — ContextProfile validation
# ---------------------------------------------------------------------------

def test_context_profile_invalid_risk_tolerance_raises():
    with pytest.raises(ValueError, match="risk_tolerance"):
        ContextProfile(project_id="p", domain="d", risk_tolerance="extreme")


def test_context_profile_invalid_style_strictness_raises():
    with pytest.raises(ValueError, match="style_strictness"):
        ContextProfile(project_id="p", domain="d", style_strictness=1.5)


def test_get_context_profile_returns_none_when_absent():
    class _Bare:
        pass
    assert get_context_profile(_Bare()) is None


def test_get_context_profile_returns_profile_when_set():
    class _Rt:
        context_profile = ContextProfile(project_id="p", domain="d")
    assert isinstance(get_context_profile(_Rt()), ContextProfile)
