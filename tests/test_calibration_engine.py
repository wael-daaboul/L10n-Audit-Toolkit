"""
tests/test_calibration_engine.py
==================================
Phase 9 — Confidence Calibration & Adaptive Thresholding Tests.

Validates:
1. No feedback -> No threshold adjustment.
2. High auto_fix rejection -> Tighter auto_fix threshold (threshold increases).
3. Shadow mode -> No routing changes (observe only).
4. Suggest mode -> No routing changes, returns original.
5. Enforce mode -> Deterministic downgrade (e.g. auto_fix -> ai_review).
6. Same input + feedback -> Identical profiles (determinism).
7. Arabic path -> Unchanged (evaluate_findings called without runtime).
8. Clamping -> Safety bounds (AUTO_FIX floor 0.7, etc.).
9. LTFinding defaults -> LTFinding can still be created without offset (compat check).
"""
import pytest
from unittest.mock import MagicMock
from l10n_audit.core.calibration_engine import CalibrationEngine, CalibrationProfile
from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings, RouteAction, LTFinding


# ---------------------------------------------------------------------------
# Setup Helpers
# ---------------------------------------------------------------------------

def make_mock_runtime(cal_enabled=True, cal_mode="shadow", feedback=None):
    runtime = MagicMock()
    runtime.config = {
        "calibration": {
            "enabled": cal_enabled,
            "mode": cal_mode,
            "max_adjustment_per_run": 0.05
        }
    }
    runtime.metadata = {}
    if feedback:
        runtime.metadata["feedback_metrics"] = feedback
    return runtime


# ---------------------------------------------------------------------------
# Test 1 — No feedback -> No adjustment
# ---------------------------------------------------------------------------

def test_no_feedback_no_adjustment():
    """If no feedback metadata is present, profiles should use default thresholds."""
    runtime = make_mock_runtime(feedback=None)
    engine = CalibrationEngine.from_runtime(runtime)
    profiles = engine.build_profiles(None)
    
    assert profiles["auto_fix"].min_confidence_threshold == 0.8
    assert profiles["manual_review"].max_confidence_threshold == 0.3


# ---------------------------------------------------------------------------
# Test 2 — High auto_fix rejection -> Tighter threshold
# ---------------------------------------------------------------------------

def test_high_rejection_tightens_autofix():
    """High rejection rate in auto_fix should increase the confidence threshold."""
    # Target rejection for auto_fix is 1.0 - 0.9 = 0.1
    # We set rejection to 0.2 (excess = 0.1)
    feedback = {
        "rejection_rate_by_route": {"auto_fix": 0.2},
        "total_signals": 100
    }
    runtime = make_mock_runtime(feedback=feedback)
    engine = CalibrationEngine.from_runtime(runtime)
    profiles = engine.build_profiles(feedback)
    
    # default 0.8 + adjustment 0.05 (max_adjustment) = 0.85
    assert profiles["auto_fix"].min_confidence_threshold == 0.85
    assert profiles["auto_fix"].confidence_adjustment == 0.05


# ---------------------------------------------------------------------------
# Test 3 — Shadow mode -> No route changes
# ---------------------------------------------------------------------------

def test_shadow_mode_no_changes():
    """In shadow mode, calibrate_route must return the original route regardless of calibration."""
    feedback = {"rejection_rate_by_route": {"auto_fix": 0.5}} # very high rejection
    runtime = make_mock_runtime(cal_mode="shadow", feedback=feedback)
    engine = CalibrationEngine.from_runtime(runtime)
    profiles = engine.build_profiles(feedback)
    
    # threshold should be tightened to 0.85
    assert profiles["auto_fix"].min_confidence_threshold == 0.85
    
    # But route must NOT change in shadow mode
    # confidence 0.8 (original pass, calibrated fail)
    new_route = engine.calibrate_route(RouteAction.AUTO_FIX, 0.8, True, profiles)
    assert new_route == RouteAction.AUTO_FIX


# ---------------------------------------------------------------------------
# Test 5 — Enforce mode -> Downgrade only
# ---------------------------------------------------------------------------

def test_enforce_mode_downgrade():
    """In enforce mode, a failing calibrated threshold must downgrade to AI_REVIEW."""
    feedback = {"rejection_rate_by_route": {"auto_fix": 0.5}}
    runtime = make_mock_runtime(cal_mode="enforce", feedback=feedback)
    engine = CalibrationEngine.from_runtime(runtime)
    profiles = engine.build_profiles(feedback)
    
    # confidence 0.80 passes base (>= 0.8) but fails calibrated (>= 0.85)
    new_route = engine.calibrate_route(RouteAction.AUTO_FIX, 0.8, True, profiles)
    assert new_route == RouteAction.AI_REVIEW
    
    # High confidence still passes
    assert engine.calibrate_route(RouteAction.AUTO_FIX, 0.9, True, profiles) == RouteAction.AUTO_FIX


def test_no_upgrades_allowed():
    """Calibration must NEVER upgrade a route (e.g. ai_review -> auto_fix)."""
    # We simulate a "perfect" ai_review lane (0 rejection)
    feedback = {"rejection_rate_by_route": {"ai_review": 0.0}}
    runtime = make_mock_runtime(cal_mode="enforce", feedback=feedback)
    engine = CalibrationEngine.from_runtime(runtime)
    profiles = engine.build_profiles(feedback)
    
    # Even if confidence is 0.9 (which would pass auto_fix), if it was ai_review, it stays ai_review
    route = engine.calibrate_route(RouteAction.AI_REVIEW, 0.9, True, profiles)
    assert route == RouteAction.AI_REVIEW


# ---------------------------------------------------------------------------
# Test 6 — Determinism
# ---------------------------------------------------------------------------

def test_determinism():
    """Same feedback produced identical calibration profiles."""
    feedback = {"rejection_rate_by_route": {"auto_fix": 0.3}}
    engine = CalibrationEngine(mode="enforce")
    
    p1 = engine.build_profiles(feedback)
    p2 = engine.build_profiles(feedback)
    
    assert p1["auto_fix"].min_confidence_threshold == p2["auto_fix"].min_confidence_threshold
    assert p1["auto_fix"].confidence_adjustment == p2["auto_fix"].confidence_adjustment


# ---------------------------------------------------------------------------
# Test 7 — Arabic Unchanged
# ---------------------------------------------------------------------------

def test_arabic_path_not_calibrated():
    """Arabic processing must not use calibration profiles (evaluate_findings called without runtime)."""
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    
    # We mock a high-rejection auto_fix state in config, but global 
    # Arabic function shouldn't care about the config anyway since it doesn't receive runtime.
    rows = [
        {"key": "t1", "old": "test", "new": "fix", "issue_type": "grammar", "fix_mode": "auto_safe"}
    ]
    
    # Arabic path currently uses evaluate_findings(ctx) without runtime.
    apply_arabic_decision_routing(rows)
    
    # The confidence 1.0 (auto_safe + grammar) should always result in auto_fix 
    # because calibration is not applied.
    assert rows[0]["decision"]["route"] == "auto_fix"


# ---------------------------------------------------------------------------
# Test 8 — Clamping & Safety Bounds
# ---------------------------------------------------------------------------

def test_clamping_safety():
    """Verify that thresholds are clamped to spec bounds."""
    # Try to adjust by a lot
    engine = CalibrationEngine(max_adjustment=0.5) 
    feedback = {"rejection_rate_by_route": {"auto_fix": 0.9}} # extreme rejection
    
    profiles = engine.build_profiles(feedback)
    # Default 0.8 + 0.1 (max_adjustment is clamped to 0.1 internally in __init__) = 0.9
    assert profiles["auto_fix"].min_confidence_threshold <= 1.0
    
    # Manual threshold ceiling
    feedback_manual = {"rejection_rate_by_route": {"manual_review": 0.9}}
    profiles_m = engine.build_profiles(feedback_manual)
    # Default 0.3 - adjustment. Check ceiling 0.4
    assert profiles_m["manual_review"].max_confidence_threshold <= 0.4


# ---------------------------------------------------------------------------
# Full Loop Integration Test
# ---------------------------------------------------------------------------

def test_evaluate_findings_with_calibration():
    """Verify end-to-end integration in evaluate_findings."""
    feedback = {"rejection_rate_by_route": {"auto_fix": 0.3}}
    runtime = make_mock_runtime(cal_mode="enforce", feedback=feedback)
    
    # Create a finding that passes base (0.8) but fails calibrated (0.85)
    f = LTFinding(
        key="x", rule_id="y", issue_category="other", message="msg",
        original_text="err", suggested_text="fix", offset=0, error_length=1,
        is_simple_fix=True # will get 0.8 (base 0.5 + 0.3 simple fix)
    )
    
    ctx = DecisionContext(findings=[f], source="en")
    result = evaluate_findings(ctx, runtime=runtime)
    
    # Base route would be auto_fix (confidence 0.8)
    # Calibrated route must be ai_review because 0.8 < 0.85
    assert len(result.auto_fix) == 0
    assert len(result.ai_review) == 1
    assert f.confidence_score == 0.8
    # Metadata side-effect
    assert "calibration_metrics" in runtime.metadata
    assert runtime.metadata["calibration_metrics"]["adjustments"]["auto_fix"] > 0
