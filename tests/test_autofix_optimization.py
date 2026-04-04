import pytest
from unittest.mock import MagicMock
from l10n_audit.fixes.apply_safe_fixes import build_fix_plan

def __mock_setup(monkeypatch, issues, respect_routing):
    """Helper to setup mocks for build_fix_plan testing."""
    runtime = MagicMock()
    runtime.metadata = {}
    runtime.config = {"decision_engine": {"respect_routing": respect_routing}}
    
    # We must ensure they process without getting filtered out by other logic.
    # The default classify_issue will require 'auto_safe' to be returned.
    def mock_classify_issue(issue):
        return "auto_safe"
    monkeypatch.setattr("l10n_audit.fixes.apply_safe_fixes.classify_issue", mock_classify_issue)

    return runtime

def test_autofix_optimization_respects_routing(monkeypatch):
    """Test reduction of fixes when flag is enabled: only 'auto_fix' passes."""
    issues = [
        {"key": "k1", "decision": {"route": "auto_fix"}, "new": "fix1"},
        {"key": "k2", "decision": {"route": "ai_review"}, "new": "fix2"},
        {"key": "k3", "decision": {"route": "manual_review"}, "new": "fix3"},
        {"key": "k4", "decision": {"route": "dropped"}, "new": "fix4"},
    ]
    
    runtime = __mock_setup(monkeypatch, issues, respect_routing=True)
    
    plan = build_fix_plan(issues, runtime=runtime)
    
    # Only k1 should be in the plan
    included_keys = [item["key"] for item in plan]
    assert included_keys == ["k1"]


def test_autofix_fallback_without_decision(monkeypatch):
    """Test fallback functionality: if an issue lacks 'decision', it defaults to 'auto_fix'."""
    issues = [
        {"key": "k1", "new": "fix1"},  # Legacy data without decision key
        {"key": "k2", "decision": {}, "new": "fix2"}, # Empty decision dict
        {"key": "k3", "decision": {"route": None}, "new": "fix3"}, # Explicit None
    ]
    
    runtime = __mock_setup(monkeypatch, issues, respect_routing=True)
    
    plan = build_fix_plan(issues, runtime=runtime)
    
    included_keys = [item["key"] for item in plan]
    assert sorted(included_keys) == ["k1", "k2", "k3"]


def test_autofix_routing_disabled_no_filter(monkeypatch):
    """Test functionality when 'respect_routing' is disabled: All issues are passed to builder."""
    issues = [
        {"key": "k1", "decision": {"route": "ai_review"}, "new": "fix1"},
        {"key": "k2", "decision": {"route": "auto_fix"}, "new": "fix2"},
        {"key": "k3", "decision": {"route": "manual_review"}, "new": "fix3"},
    ]
    
    runtime = __mock_setup(monkeypatch, issues, respect_routing=False)
    
    plan = build_fix_plan(issues, runtime=runtime)
    
    included_keys = [item["key"] for item in plan]
    assert sorted(included_keys) == ["k1", "k2", "k3"]


def test_metrics_injected_to_metadata(monkeypatch):
    """Test that skipped calls increment the would_skip_autofix metric."""
    issues = [
        {"key": "k1", "decision": {"route": "auto_fix"}, "new": "fix1"},
        {"key": "k2", "decision": {"route": "ai_review"}, "new": "fix2"},
        {"key": "k3", "decision": {"route": "dropped"}, "new": "fix3"},
    ]
    
    runtime = __mock_setup(monkeypatch, issues, respect_routing=True)
    
    build_fix_plan(issues, runtime=runtime)
    
    assert "routing_metrics_autofix" in runtime.metadata
    metrics_dict = runtime.metadata["routing_metrics_autofix"]
    
    assert metrics_dict["would_skip_autofix"] == 2
    assert metrics_dict["would_skip_ai"] == 0
    assert metrics_dict["total"] == 3
    assert metrics_dict["by_route"]["auto_fix"] == 1
    assert metrics_dict["by_route"]["ai_review"] == 1
    assert metrics_dict["by_route"]["dropped"] == 1
