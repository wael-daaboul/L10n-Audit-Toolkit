import pytest
from unittest.mock import MagicMock
from l10n_audit.core.enforcement_layer import EnforcementController

def create_mock_runtime(enabled: bool):
    runtime = MagicMock()
    runtime.metadata = {}
    runtime.config = {"decision_engine": {"respect_routing": enabled}}
    return runtime

def test_unified_routing_disabled():
    """Test functionality when routing is disabled globally. Everything must pass."""
    runtime = create_mock_runtime(enabled=False)
    enforcer = EnforcementController(runtime)

    assert enforcer.should_process("ai_review", "ai") is True
    assert enforcer.should_process("auto_fix", "ai") is True
    assert enforcer.should_process("dropped", "ai") is True
    
    assert enforcer.should_process("ai_review", "autofix") is True
    assert enforcer.should_process("auto_fix", "autofix") is True

def test_unified_ai_enforcement():
    """Test reduction of AI calls when flag is enabled: auto_fix and drops are skipped."""
    runtime = create_mock_runtime(enabled=True)
    enforcer = EnforcementController(runtime)

    assert enforcer.should_process("ai_review", "ai") is True
    assert enforcer.should_process("auto_fix", "ai") is False
    assert enforcer.should_process("manual_review", "ai") is False
    assert enforcer.should_process("dropped", "ai") is False

def test_unified_autofix_enforcement():
    """Test only 'auto_fix' passes when checking the autofix stage."""
    runtime = create_mock_runtime(enabled=True)
    enforcer = EnforcementController(runtime)

    assert enforcer.should_process("auto_fix", "autofix") is True
    assert enforcer.should_process("ai_review", "autofix") is False
    assert enforcer.should_process("manual_review", "autofix") is False
    assert enforcer.should_process("dropped", "autofix") is False

def test_unified_fallback_without_decision():
    """Test fallback functionality: if an issue lacks 'decision', it defaults to the host stage type."""
    runtime = create_mock_runtime(enabled=True)
    enforcer = EnforcementController(runtime)

    # Route is None -> falls back to "ai_review" inside AI
    assert enforcer.should_process(None, "ai") is True
    
    # Route is None -> falls back to "auto_fix" inside Autofix
    assert enforcer.should_process(None, "autofix") is True

def test_unified_metrics_correctness():
    """Test metrics logic increment appropriately accurately."""
    runtime = create_mock_runtime(enabled=True)
    enforcer = EnforcementController(runtime)

    enforcer.record("ai_review")
    enforcer.record("auto_fix")
    enforcer.record(None)
    
    enforcer.record_skip("ai")
    enforcer.record_skip("ai")
    enforcer.record_skip("autofix")

    enforcer.save_metrics(runtime)
    
    assert "routing_metrics_unified" in runtime.metadata
    metrics = runtime.metadata["routing_metrics_unified"]

    assert metrics["total"] == 3
    assert metrics["by_route"]["ai_review"] == 1
    assert metrics["by_route"]["auto_fix"] == 1
    assert metrics["by_route"]["unknown"] == 1
    
    assert metrics["skipped_ai"] == 2
    assert metrics["skipped_autofix"] == 1

    # Check that backwards compatibility aliases are preserved
    assert "routing_metrics" in runtime.metadata
    assert "routing_metrics_autofix" in runtime.metadata
    assert runtime.metadata["routing_metrics"]["would_skip_ai"] == 2
    assert runtime.metadata["routing_metrics_autofix"]["would_skip_autofix"] == 1
