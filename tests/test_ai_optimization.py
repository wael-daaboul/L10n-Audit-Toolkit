import pytest
import sys
from unittest.mock import MagicMock

# Mock litellm to avoid ModuleNotFoundError during test collection
sys.modules["litellm"] = MagicMock()

from l10n_audit.core.routing_metrics import RoutingMetrics
from l10n_audit.audits.ai_review import run_stage
from l10n_audit.models import AuditOptions
from unittest.mock import MagicMock

def __mock_setup(monkeypatch, issues, respect_routing):
    """Helper to setup mocks for run_stage"""
    calls = []
    
    # Mock runtime
    runtime = MagicMock()
    runtime.config = {"decision_engine": {"respect_routing": respect_routing}}
    
    options = MagicMock()
    options.ai_review = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "mock"
    options.ai_review.translate_missing = False
    options.ai_review.batch_size = 50
    
    # Define an ai_provider mock corresponding to the AIProvider interface
    ai_provider = MagicMock()
    
    def fake_batch_review(issues_batch, *args, **kwargs):
        for item in issues_batch:
            calls.append(item["key"])
        return []
        
    ai_provider.review_batch.side_effect = fake_batch_review
    # Alias in case the method is named differently (e.g., execute, run)
    ai_provider.run_batch_review.side_effect = fake_batch_review
    ai_provider.review.side_effect = fake_batch_review

    monkeypatch.setattr("l10n_audit.core.validators.validate_ai_config", lambda **kwargs: {})

    # Bypass file loading logic which crashes on mock runtime
    monkeypatch.setattr("l10n_audit.audits.ai_review.load_locale_mapping", lambda *a, **kw: {i["key"]: "Normal english text for testing" for i in issues})

    # Bypass file writes
    monkeypatch.setattr("l10n_audit.audits.ai_review.write_json", lambda d, p: None)

    return runtime, options, calls, ai_provider


def test_ai_optimization_respects_routing(monkeypatch):
    """Test reduction of AI calls when flag is enabled: auto_fix and manual_review are skipped."""
    issues = [
        {"key": "k1", "decision": {"route": "ai_review"}},
        {"key": "k2", "decision": {"route": "auto_fix"}},
        {"key": "k3", "decision": {"route": "manual_review"}},
        {"key": "k4", "decision": {"route": "dropped"}},
    ]

    runtime, options, calls, ai_provider = __mock_setup(monkeypatch, issues, respect_routing=True)

    run_stage(runtime, options, ai_provider=ai_provider, previous_issues=issues)

    assert calls == ["k1"]


def test_ai_fallback_without_decision(monkeypatch):
    """Issues without semantic/missing signals should not invoke AI even in fallback mode."""
    issues = [
        {"key": "k1"},  # Legacy data without decision key
        {"key": "k2", "decision": {}}, # Empty decision dict
        {"key": "k3", "decision": {"route": None}}, # Explicit None string or object
    ]

    runtime, options, calls, ai_provider = __mock_setup(monkeypatch, issues, respect_routing=True)

    run_stage(runtime, options, ai_provider=ai_provider, previous_issues=issues)

    assert calls == []


def test_ai_routing_disabled_no_filter(monkeypatch):
    """Routing disabled still honors invocation control, so only eligible issues call AI."""
    issues = [
        {"key": "k1", "decision": {"route": "ai_review"}},
        {"key": "k2", "decision": {"route": "auto_fix"}},
        {"key": "k3", "decision": {"route": "manual_review"}},
    ]

    runtime, options, calls, ai_provider = __mock_setup(monkeypatch, issues, respect_routing=False)

    run_stage(runtime, options, ai_provider=ai_provider, previous_issues=issues)

    assert sorted(calls) == ["k1"]


def test_metrics(monkeypatch):
    """Test that skipped AI calls increment the would_skip_ai metric."""
    issues = [
        {"key": "k1", "decision": {"route": "ai_review"}},
        {"key": "k2", "decision": {"route": "auto_fix"}},
    ]

    runtime, options, calls, ai_provider = __mock_setup(monkeypatch, issues, respect_routing=True)
    
    # We must access the metrics log or metadata. The code injects it into runtime.metadata["routing_metrics"]
    runtime.metadata = {}

    run_stage(runtime, options, ai_provider=ai_provider, previous_issues=issues)

    assert "routing_metrics" in runtime.metadata
    metrics_dict = runtime.metadata["routing_metrics"]
    
    assert metrics_dict["would_skip_ai"] == 1
    assert metrics_dict["total"] == 2
    assert metrics_dict["by_route"]["ai_review"] == 1
    assert metrics_dict["by_route"]["auto_fix"] == 1
