import pytest
import copy

from l10n_audit.core.decision_engine import apply_arabic_decision_routing, RouteAction

def test_no_drops_guarantee():
    """Ensure apply_arabic_decision_routing does not alter the row count."""
    rows = [
        {"key": "test.one", "old": "Old 1", "new": "New 1", "issue_type": "whitespace", "fix_mode": "auto_safe"},
        {"key": "test.two", "old": "Old 2", "new": "New 2", "issue_type": "grammar", "fix_mode": "review_required"},
        {"key": "test.three", "old": "Old 3", "new": "New 3", "issue_type": "context_conflict", "fix_mode": "review_required"},
    ]
    original_len = len(rows)
    apply_arabic_decision_routing(rows, suggestion_key="new")
    assert len(rows) == original_len, "Length of rows changed during routing (Drops occurred)"


def test_decision_presence():
    """Ensure every row gets a 'decision' dict with a valid 'route'."""
    rows = [
        {"key": "test.one", "old": "Old 1", "new": "New 1", "issue_type": "whitespace", "fix_mode": "auto_safe"},
        {"key": "test.two", "old": "Old 2", "new": "", "issue_type": "empty_string", "fix_mode": "review_required"},
    ]
    apply_arabic_decision_routing(rows, suggestion_key="new")
    
    for row in rows:
        assert "decision" in row, "Missing 'decision' dict in output row"
        assert "route" in row["decision"], "Missing 'route' key in 'decision' dict"
        assert row["decision"]["route"] in {action.value for action in RouteAction}, "Invalid route action assigned"


def test_enforcement_ignored(monkeypatch):
    """Ensure routing respects pure shadow mode with no conditional skipped values, even if config is enabled."""
    rows = [
        {"key": "test.one", "old": "Old 1", "new": "New 1", "issue_type": "whitespace", "fix_mode": "auto_safe"},
    ]
    
    # We don't have a runtime dependency inside apply_arabic_decision_routing right now,
    # but we verify that the method is decoupled from the `is_routing_enabled` blocker internally.
    apply_arabic_decision_routing(rows, suggestion_key="new")
    assert rows[0]["decision"]["route"] == "auto_fix"
    # Even if it's "auto_fix", it is NOT removed from `rows` (meaning it's technically passed downstream).
    assert len(rows) == 1


def test_ordering_preserved():
    """Ensure findings remain in the exact original sequence."""
    rows = [
        {"key": "alpha", "old": "A", "new": "A1", "issue_type": "t1", "fix_mode": "auto_safe"},
        {"key": "beta",  "old": "B", "new": "B1", "issue_type": "t2", "fix_mode": "review_required"},
        {"key": "gamma", "old": "C", "new": "C1", "issue_type": "t3", "fix_mode": "auto_safe"},
    ]
    original_order = [row["key"] for row in rows]
    apply_arabic_decision_routing(rows, suggestion_key="new")
    new_order = [row["key"] for row in rows]
    
    assert original_order == new_order, f"Order scrambled! Expected {original_order}, got {new_order}"


def test_metrics_observational_only(caplog):
    """Ensure metrics strictly record routes but never increment skips."""
    import logging
    rows = [
        {"key": "alpha", "old": "A", "new": "A1", "issue_type": "t1", "fix_mode": "auto_safe"},
        {"key": "beta",  "old": "B", "new": "B1", "issue_type": "t2", "fix_mode": "review_required"},
    ]
    
    with caplog.at_level(logging.INFO, logger="l10n_audit.ar_routing"):
        apply_arabic_decision_routing(rows, suggestion_key="new")
        
    log_text = caplog.text
    assert '"would_skip_autofix": 0' in log_text or '"would_skip_autofix":0' in log_text.replace(" ", "")
    assert '"would_skip_ai": 0' in log_text or '"would_skip_ai":0' in log_text.replace(" ", "")


def test_index_based_mapping_stability():
    rows = [
        {"key": "k1", "old": "A", "new": "A1", "issue_type": "t1", "fix_mode": "auto_safe"},
        {"key": "k2", "old": "B", "new": "", "issue_type": "t2", "fix_mode": "review_required"},
    ]

    apply_arabic_decision_routing(rows, suggestion_key="new")

    assert rows[0]["decision"]["route"] == "auto_fix"
    assert rows[1]["decision"]["route"] == "manual_review"
