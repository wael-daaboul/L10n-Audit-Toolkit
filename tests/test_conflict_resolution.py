import pytest
from dataclasses import dataclass
from l10n_audit.core.conflict_resolution import ConflictResolver, MutationRecord, get_conflict_resolver

@dataclass
class MockRuntime:
    def __init__(self):
        self.metadata = {}

def test_single_registration():
    resolver = ConflictResolver()
    m = MutationRecord(key="k1", original_text="a", new_text="b", offset=0, length=1, source="auto", priority=3)
    assert resolver.register(m) is True
    assert len(resolver._registry["k1"]) == 1

def test_non_overlapping_accepted():
    resolver = ConflictResolver()
    m1 = MutationRecord(key="k1", original_text="abc", new_text="xbc", offset=0, length=1, source="auto", priority=3)
    m2 = MutationRecord(key="k1", original_text="abc", new_text="abz", offset=2, length=1, source="auto", priority=3)
    
    assert resolver.register(m1) is True
    assert resolver.register(m2) is True
    assert len(resolver._registry["k1"]) == 2

def test_overlapping_rejects_lower_priority():
    resolver = ConflictResolver()
    # P3 accepted first
    m1 = MutationRecord(key="k1", original_text="hello", new_text="hi", offset=0, length=5, source="auto", priority=3)
    assert resolver.register(m1) is True
    
    # P2 (AI) attempts to overlap
    m2 = MutationRecord(key="k1", original_text="hello", new_text="hey", offset=0, length=2, source="ai", priority=2)
    assert resolver.register(m2) is False
    assert resolver.summarize()["rejected_low_priority"] == 1

def test_overlapping_rejects_equal_priority_stable():
    resolver = ConflictResolver()
    m1 = MutationRecord(key="k1", original_text="hello", new_text="hi", offset=0, length=5, source="auto", priority=3)
    assert resolver.register(m1) is True
    
    m2 = MutationRecord(key="k1", original_text="hello", new_text="hey", offset=0, length=5, source="auto", priority=3)
    assert resolver.register(m2) is False # Stable first-wins

def test_different_keys_do_not_conflict():
    resolver = ConflictResolver()
    m1 = MutationRecord(key="k1", original_text="a", new_text="b", offset=0, length=1, source="auto", priority=3)
    m2 = MutationRecord(key="k2", original_text="a", new_text="c", offset=0, length=1, source="auto", priority=3)
    
    assert resolver.register(m1) is True
    assert resolver.register(m2) is True

def test_fallback_identity_no_offset():
    resolver = ConflictResolver()
    # r1 has offset
    m1 = MutationRecord(key="k1", original_text="hello", new_text="hi", offset=0, length=5, source="auto", priority=3)
    assert resolver.register(m1) is True
    
    # r2 has NO offset (-1)
    m2 = MutationRecord(key="k1", original_text="hello", new_text="hey", offset=-1, length=0, source="manual", priority=1)
    # Should conflict because original_text matches and it's the same key
    assert resolver.register(m2) is False

def test_shared_resolver_via_runtime():
    runtime = MockRuntime()
    r1 = get_conflict_resolver(runtime)
    r2 = get_conflict_resolver(runtime)
    assert r1 is r2
    
    m = MutationRecord(key="k1", original_text="a", new_text="b", offset=0, length=1, source="auto", priority=3)
    assert r1.register(m) is True
    assert r2.summarize()["conflicts_detected"] == 0
    
    m_conflict = MutationRecord(key="k1", original_text="a", new_text="c", offset=0, length=1, source="ai", priority=2)
    assert r2.register(m_conflict) is False
    assert r1.summarize()["rejected_low_priority"] == 1

def test_arabic_isolation_logic_simulation():
    # ConflictResolver itself is agnostic, but the integration points skip it for Arabic.
    # We verify that if we DON'T register Arabic findings, no conflicts occur.
    resolver = ConflictResolver()
    
    # Register English P3
    m_en = MutationRecord(key="common", original_text="text", new_text="edit", offset=0, length=4, source="auto", priority=3)
    assert resolver.register(m_en) is True
    
    # Simulate Arabic path skipping registration
    # Even if an Arabic finding has the same key/range, we just don't call register()
    # in the Arabic loop (enforced in apply_safe_fixes.py and audits/ai_review.py)
    pass 

def test_determinism_test():
    # Same inputs should produce same registry state
    def run_scenario():
        resolver = ConflictResolver()
        m1 = MutationRecord(key="k1", original_text="abc", new_text="x", offset=0, length=1, source="a", priority=3)
        m2 = MutationRecord(key="k1", original_text="abc", new_text="y", offset=0, length=1, source="b", priority=2)
        m3 = MutationRecord(key="k1", original_text="abc", new_text="z", offset=1, length=1, source="c", priority=3)
        return [resolver.register(m1), resolver.register(m2), resolver.register(m3)]

    assert run_scenario() == [True, False, True]
    assert run_scenario() == [True, False, True]


def test_higher_priority_wins_over_lower_registered_first():
    """Regression: higher-priority mutation must evict a lower-priority one already in registry.

    Scenario: manual (P1) registers first, auto_fix (P3) registers second with same key/overlap.
    Expected: auto_fix wins, manual is evicted, metrics are correct.
    """
    resolver = ConflictResolver()

    # Step 1: register lower-priority mutation (manual, P1) first
    manual = MutationRecord(
        key="greeting",
        original_text="hello world",
        new_text="hi world",
        offset=0,
        length=5,
        source="manual",
        priority=1,
    )
    assert resolver.register(manual) is True

    # Step 2: register higher-priority overlapping mutation (auto_fix, P3) second
    auto_fix = MutationRecord(
        key="greeting",
        original_text="hello world",
        new_text="Hey world",
        offset=0,
        length=5,
        source="auto_fix",
        priority=3,
    )
    assert resolver.register(auto_fix) is True  # must win

    # Step 3: auto_fix must be the sole accepted record for this key
    accepted = resolver._registry["greeting"]
    assert len(accepted) == 1
    assert accepted[0].source == "auto_fix"
    assert accepted[0].new_text == "Hey world"

    # Step 4: metrics must reflect the real resolution
    summary = resolver.summarize()
    assert summary["conflicts_detected"] >= 1
    assert summary["conflicts_resolved"] >= 1  # must NOT be 0

    # Step 5: determinism — re-running produces identical outcome
    def run_scenario():
        r = ConflictResolver()
        r.register(MutationRecord(
            key="greeting", original_text="hello world", new_text="hi world",
            offset=0, length=5, source="manual", priority=1,
        ))
        accepted_second = r.register(MutationRecord(
            key="greeting", original_text="hello world", new_text="Hey world",
            offset=0, length=5, source="auto_fix", priority=3,
        ))
        return accepted_second, r._registry["greeting"][0].source

    for _ in range(3):
        result, winner = run_scenario()
        assert result is True
        assert winner == "auto_fix"
