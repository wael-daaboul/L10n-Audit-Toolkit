"""
tests/test_decision_engine.py
=============================
Unit tests for the Phase 1 decision engine seam (Shadow Mode).
"""
from typing import Any
import pytest

from l10n_audit.core.languagetool_layer import LTFinding
from l10n_audit.core.decision_engine import DecisionContext, DecisionResult, evaluate_findings, RouteAction
from l10n_audit.audits.en_grammar_audit import build_languagetool_findings, _lt_finding_to_audit_dict


def test_evaluate_findings_rules() -> None:
    finding_empty_sugg = LTFinding(
        key="k1", rule_id="R1", issue_category="grammar", message="m",
        original_text="o", suggested_text="", offset=0, error_length=1, is_simple_fix=True
    )
    finding_safe_fix = LTFinding(
        key="k2", rule_id="R2", issue_category="style", message="m",
        original_text="o", suggested_text="safe", offset=0, error_length=1, is_simple_fix=True
    )
    finding_ai_review = LTFinding(
        key="k3", rule_id="R3", issue_category="style", message="m",
        original_text="o", suggested_text="risky", offset=0, error_length=1, is_simple_fix=False
    )
    
    ctx = DecisionContext(findings=[finding_empty_sugg, finding_safe_fix, finding_ai_review], source="en")
    result = evaluate_findings(ctx)
    
    assert result.manual_review == [finding_empty_sugg]
    assert result.auto_fix == [finding_safe_fix]
    assert result.ai_review == [finding_ai_review]
    assert result.dropped == []


def test_integration_safety_en_grammar_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    # We mock the entire `get_languagetool_layer` to return a fake layer 
    # that always yields predictable mock findings matching different rule routes.
    from types import SimpleNamespace
    finding1 = LTFinding(
        key="app.title", rule_id="R1", issue_category="grammar", message="bad grammar",
        original_text="Hello world", suggested_text="Hello, world", offset=0, error_length=11, 
        is_simple_fix=True, replacements_str="Hello, world", match_context="Hello world context"
    )
    finding2 = LTFinding(
        key="app.desc", rule_id="R2", issue_category="style", message="bad style",
        original_text="Some description", suggested_text="", offset=5, error_length=16, 
        is_simple_fix=False, replacements_str="", match_context="Some description context"
    )

    class FakeLayer:
        @property
        def session_mode(self) -> str:
            return "mocked-mode"
        @property
        def session_note(self) -> str | None:
            return "mocked-note"
        def analyze_text_batch(self, pairs, strict=False):
            key = pairs[0][0]
            if key == "app.title":
                return [finding1]
            if key == "app.desc":
                return [finding2]
            return []
        def close(self):
            pass

    monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.get_languagetool_layer", lambda *a, **kw: FakeLayer())
    
    try:
        monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.check_java_available", lambda: True)
    except AttributeError:
        pass

    text_by_key = [("app.title", "Hello world"), ("app.desc", "Some description")]
    runtime = SimpleNamespace()

    mode, findings, note = build_languagetool_findings(text_by_key, runtime)
    
    assert mode == "mocked-mode"
    assert note == "mocked-note"
    assert len(findings) == 2  # CRITICAL: Ensures no items dropped!

    # Verify additive decision metadata is injected
    assert findings[0]["decision"]["route"] == RouteAction.AUTO_FIX
    assert findings[1]["decision"]["route"] == RouteAction.MANUAL_REVIEW

    # Assert output BEFORE + additive metadata = output AFTER 
    expected_1 = _lt_finding_to_audit_dict(finding1, RouteAction.AUTO_FIX)
    expected_2 = _lt_finding_to_audit_dict(finding2, RouteAction.MANUAL_REVIEW)

    assert findings[0] == expected_1
    assert findings[1] == expected_2


def test_ordering_stability_same_offset_across_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    
    # Create 3 findings with the SAME offset, but destined for DIFFERENT routes.
    f_auto_fix = LTFinding(
        key="app.test", rule_id="R1", issue_category="grammar", message="m1",
        original_text="Hello", suggested_text="fix", offset=0, error_length=2, 
        is_simple_fix=True, replacements_str="fix", match_context="c"
    )
    f_ai_review = LTFinding(
        key="app.test", rule_id="R2", issue_category="style", message="m2",
        original_text="Hello", suggested_text="risky", offset=0, error_length=2, 
        is_simple_fix=False, replacements_str="risky", match_context="c"
    )
    f_manual = LTFinding(
        key="app.test", rule_id="R3", issue_category="style", message="m3",
        original_text="Hello", suggested_text="", offset=0, error_length=2, 
        is_simple_fix=False, replacements_str="", match_context="c"
    )

    # Input order: manual -> ai -> auto (intentionally reversed vs queue order)
    mock_findings = [f_manual, f_ai_review, f_auto_fix]

    class FakeLayer:
        @property
        def session_mode(self) -> str: return "mocked-mode"
        @property
        def session_note(self) -> str | None: return "mocked-note"
        def analyze_text_batch(self, pairs, strict=False):
            return mock_findings
        def close(self): pass

    monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.get_languagetool_layer", lambda *a, **kw: FakeLayer())
    try:
        monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.check_java_available", lambda: True)
    except AttributeError:
        pass

    text_by_key = [("app.test", "Hello")]
    mode, findings, note = build_languagetool_findings(text_by_key, SimpleNamespace())

    # 1. Assert no silent drops
    assert len(findings) == len(mock_findings)

    # 2. Output order MUST match exactly original order
    findings_order_is_identical_to_input = (
        findings[0]["rule_id"] == "R3" and
        findings[1]["rule_id"] == "R2" and
        findings[2]["rule_id"] == "R1"
    )
    assert findings_order_is_identical_to_input
    
    # 3. Assert correct routes applied just to be sure
    assert findings[0]["decision"]["route"] == RouteAction.MANUAL_REVIEW
    assert findings[1]["decision"]["route"] == RouteAction.AI_REVIEW
    assert findings[2]["decision"]["route"] == RouteAction.AUTO_FIX


def test_routing_disabled_default() -> None:
    """Ensure that system runs in 100% legacy shadow mode unless explicitly overridden."""
    from l10n_audit.core.decision_engine import is_routing_enabled
    from types import SimpleNamespace
    
    # 1. No config attribute at all
    empty_runtime = SimpleNamespace()
    assert is_routing_enabled(empty_runtime) is False
    
    # 2. Config without decision_engine
    runtime_no_de = SimpleNamespace(config={"some_other_plugin": True})
    assert is_routing_enabled(runtime_no_de) is False
    
    # 3. Explicitly disabled in config
    runtime_disabled = SimpleNamespace(config={"decision_engine": {"respect_routing": False}})
    assert is_routing_enabled(runtime_disabled) is False
    
    # 4. Explicitly enabled
    runtime_enabled = SimpleNamespace(config={"decision_engine": {"respect_routing": True}})
    assert is_routing_enabled(runtime_enabled) is True


def test_routing_enforcement_active(caplog: pytest.LogCaptureFixture) -> None:
    """Ensure that apply_safe_fixes actively skips findings not destined for auto_fix when routing is enabled."""
    import logging
    from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
    from types import SimpleNamespace
    
    runtime = SimpleNamespace(config={"decision_engine": {"respect_routing": True}}, metadata={})
    
    issues = [
         {"key": "test.ai.skips", "source": "locale_qc", "issue_type": "whitespace", "decision": {"route": "ai_review"}, "details": {"old": " bad ", "new": "bad"}},
         {"key": "test.manual", "source": "locale_qc", "issue_type": "whitespace", "decision": {"route": "manual_review"}, "details": {"old": " a ", "new": "a"}},
         {"key": "test.auto.keeps", "source": "locale_qc", "issue_type": "whitespace", "decision": {"route": "auto_fix"}, "details": {"old": " a ", "new": "a"}},
    ]
    
    with caplog.at_level(logging.DEBUG):
        plan = build_fix_plan(issues, project_root=None, runtime=runtime)
        
    # Validation 1: It must log the skip enforcement
    assert "Skipping key='test.ai.skips' because route is 'ai_review' (not auto_fix)" in caplog.text
    
    # Validation 2: It must ACTUALLY drop the finding in Phase 3
    assert len(plan) == 1
    assert plan[0]["key"] == "test.auto.keeps"


def test_invariant_conservation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicitly verify that total input equals total mapped outputs regardless of routes."""
    from types import SimpleNamespace
    
    f1 = LTFinding(key="k", rule_id="1", issue_category="g", message="m", original_text="o", suggested_text="f", offset=0, error_length=1, is_simple_fix=True, replacements_str="", match_context="")
    f2 = LTFinding(key="k", rule_id="2", issue_category="g", message="m", original_text="o", suggested_text="", offset=1, error_length=1, is_simple_fix=False, replacements_str="", match_context="")
    
    class FakeLayer:
        @property
        def session_mode(self) -> str: return "m"
        @property
        def session_note(self) -> str | None: return "n"
        def analyze_text_batch(self, pairs, strict=False):
            return [f1, f2]
        def close(self): pass

    monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.get_languagetool_layer", lambda *a, **kw: FakeLayer())
    try:
        monkeypatch.setattr("l10n_audit.audits.en_grammar_audit.check_java_available", lambda: True)
    except AttributeError: pass
    
    # If the invariant `assert total_in == total_out` failed inside en_grammar_audit, this would blow up.
    build_languagetool_findings([("k", "v")], SimpleNamespace())


def test_metrics_collection_counts() -> None:
    """Test the raw structured RoutingMetrics counters independently."""
    from l10n_audit.core.routing_metrics import RoutingMetrics
    metrics = RoutingMetrics()
    
    metrics.record("auto_fix")
    metrics.record("auto_fix")
    metrics.record("ai_review")
    metrics.record("manual_review")
    
    metrics.record_autofix_skip()
    metrics.record_ai_skip()
    metrics.record_ai_skip()
    
    data = metrics.to_dict()
    assert data["total"] == 4
    assert data["by_route"]["auto_fix"] == 2
    assert data["by_route"]["ai_review"] == 1
    assert data["by_route"]["manual_review"] == 1
    assert data["would_skip_autofix"] == 1
    assert data["would_skip_ai"] == 2


def test_routing_disabled_no_change() -> None:
    """Test that applying fixes does absolutely no filtering when routing is disabled."""
    from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
    from types import SimpleNamespace
    
    runtime = SimpleNamespace(config={"decision_engine": {"respect_routing": False}}, metadata={})
    issues = [
        {"key": "k1", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "auto_fix"}, "details": {"old": "a", "new": "b"}},
        {"key": "k2", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "ai_review"}, "details": {"old": "a", "new": "b"}},
        {"key": "k3", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "manual_review"}, "details": {"old": "a", "new": "b"}}
    ]
    
    # Run the fix plan
    plan = build_fix_plan(issues, runtime=runtime)
    
    # Asserting NO skips occurred (in/out count is identical)
    assert len(plan) == 3
    assert {i["key"] for i in plan} == {"k1", "k2", "k3"}


def test_metrics_accuracy_and_ordering() -> None:
    """Simulate routing enabled and verify metadata output matches expected filtered elements while preserving order."""
    from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
    from types import SimpleNamespace
    
    runtime = SimpleNamespace(config={"decision_engine": {"respect_routing": True}}, metadata={})
    issues = [
        {"key": "k1", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "auto_fix"}, "details": {"old": "a", "new": "b"}},
        {"key": "k2", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "ai_review"}, "details": {"old": "a", "new": "b"}},
        {"key": "k3", "source": "locale_qc", "issue_type": "ws", "decision": {"route": "auto_fix"}, "details": {"old": "a", "new": "b"}}
    ]
    
    # Apply soft routing logic
    plan = build_fix_plan(issues, runtime=runtime)
    
    # Output must have exact same ordering of kept elements
    assert len(plan) == 2
    assert plan[0]["key"] == "k1"
    assert plan[1]["key"] == "k3"
    
    # Verify metadata captured the stats accurately
    metrics = runtime.metadata.get("routing_metrics")
    assert metrics is not None, "Metadata missing routing_metrics"
    
    assert metrics["total"] == 3
    assert metrics["would_skip_autofix"] == 1 # Since k2 skipped
    assert metrics["by_route"]["auto_fix"] == 2
    assert metrics["by_route"]["ai_review"] == 1


def test_arabic_pipeline_decision_injection() -> None:
    """Test that Arabic decision routing logic successfully injects metadata without dropping any findings."""
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    
    rows = [
        {"key": "k1", "issue_type": "some_err", "message": "msg1", "old": "x", "new": "y", "fix_mode": "auto_safe"},
        {"key": "k2", "issue_type": "some_err", "message": "msg2", "old": "x", "new": "", "fix_mode": "review_required"},
        {"key": "k3", "issue_type": "some_err", "message": "msg3", "old": "x"} # no suggestion
    ]
    
    # 1. Capture original lengths and states
    input_length = len(rows)
    
    # 2. Apply metadata
    apply_arabic_decision_routing(rows, suggestion_key="new")
    
    # Validation A: No Drops Guarantee
    assert len(rows) == input_length
    
    # Validation B: Decision Presence
    for row in rows:
        assert "decision" in row
        assert "route" in row["decision"]
        assert row["decision"]["route"] in {"auto_fix", "ai_review", "manual_review"}
    
    # Verify accurate routes based on generic rules
    assert rows[0]["decision"]["route"] == "auto_fix"     # Has "new" and fix_mode "auto_safe"
    assert rows[1]["decision"]["route"] == "manual_review" # Has empty "new" -> rule_empty_suggestion -> manual_review
    assert rows[2]["decision"]["route"] == "manual_review" # No "new" -> get("new", "") == "" -> empty -> manual_review
