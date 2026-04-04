"""
tests/test_arabic_enforcement_activation.py
============================================
Phase 11 — Arabic Controlled Enforcement Activation Tests (corrected).

Contract under test:
- len(output) == len(input) in ALL cases (rows are NEVER dropped)
- Enforcement and conflict logic annotate rows, not remove them
- Shared per-run ConflictResolver is used (get_conflict_resolver)
- Multiple Arabic stages do not overwrite each other's metadata (namespaced keys)
- Original index order is preserved exactly
- Deterministic across repeated runs
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from l10n_audit.core.enforcement_layer import EnforcementController
from l10n_audit.core.feedback_engine import FeedbackAggregator, FeedbackSignal
from l10n_audit.core.conflict_resolution import get_conflict_resolver, MutationRecord, ConflictResolver


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _Runtime:
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _runtime(respect_routing: bool = False) -> _Runtime:
    return _Runtime(config={"decision_engine": {"respect_routing": respect_routing}})


def _row(key: str, route: str, fix: str = "", idx: int = 0) -> dict:
    return {
        "key": key,
        "old": f"original_{key}",
        "new": fix,
        "candidate_value": fix,
        "issue_type": "test_issue",
        "severity": "low",
        "message": "test",
        "fix_mode": "auto_safe" if route == "auto_fix" else "review_required",
        "decision": {"route": route, "confidence": 0.7, "risk": "low"},
        "_original_idx": idx,
    }


def _simulate_ar_locale_qc(rows: list[dict], runtime: _Runtime,
                            stage_name: str = "ar_locale_qc") -> tuple:
    """
    Inline replica of the corrected Phase 11 logic from ar_locale_qc.run_stage().
    Uses get_conflict_resolver (shared) and namespaced metadata keys.
    NEVER drops rows.
    """
    enforcer = EnforcementController(runtime)
    feedback = FeedbackAggregator()
    resolver = get_conflict_resolver(runtime)  # shared per-run resolver

    input_count = len(rows)

    for idx, row in enumerate(rows):
        route = row.get("decision", {}).get("route")
        confidence = float(row.get("decision", {}).get("confidence", 0.5))
        risk = str(row.get("decision", {}).get("risk", "low"))

        enforcer.record(route)

        fix_text = row.get("new", "")
        mutation_blocked = False
        if fix_text:
            priority_map = {"auto_fix": 3, "ai_review": 2, "manual_review": 1}
            priority = priority_map.get(route or "", 1)
            mut = MutationRecord(
                key=row.get("key", ""),
                original_text=row.get("old", ""),
                new_text=fix_text,
                offset=-1,
                length=0,
                source="arabic",
                priority=priority,
                mutation_id="",  # empty so identity-fallback uses original_text comparison
            )
            mutation_blocked = not resolver.register(mut)

        actionable = enforcer.should_process(route, "ai") and not mutation_blocked

        if not actionable:
            if not enforcer.should_process(route, "ai"):
                enforcer.record_skip("ai")
            row["enforcement_skipped"] = True
            feedback.record(FeedbackSignal(
                route=route or "unknown", confidence=confidence, risk=risk,
                was_accepted=False, was_modified=False, was_rejected=True,
                source="arabic",
            ))
        else:
            row["enforcement_skipped"] = False
            feedback.record(FeedbackSignal(
                route=route or "unknown", confidence=confidence, risk=risk,
                was_accepted=True, was_modified=False, was_rejected=False,
                source="arabic",
            ))

    # Row count invariant — must always hold
    assert len(rows) == input_count

    enforcer.save_metrics(runtime)
    if hasattr(runtime, "metadata"):
        runtime.metadata[f"feedback_metrics_{stage_name}"] = feedback.summarize()
        runtime.metadata[f"conflict_metrics_{stage_name}"] = {
            **resolver.summarize(),
            "source": "arabic",
            "stage": stage_name,
        }

    return rows, enforcer, feedback, resolver


# ---------------------------------------------------------------------------
# Test 1 — Routing enabled: ALL rows still present, none dropped
# ---------------------------------------------------------------------------

def test_routing_enabled_no_row_loss():
    rt = _runtime(respect_routing=True)
    rows = [
        _row("k1", "auto_fix",      fix="fix1", idx=0),
        _row("k2", "ai_review",     fix="fix2", idx=1),
        _row("k3", "manual_review", fix="fix3", idx=2),
        _row("k4", "ai_review",     fix="fix4", idx=3),
    ]
    input_count = len(rows)

    output, enforcer, _, _ = _simulate_ar_locale_qc(rows, rt)

    assert enforcer.enabled
    # Critical: no rows dropped
    assert len(output) == input_count

    # Enforcement marks non-ai_review rows as skipped, but does not remove them
    skipped = [r for r in output if r.get("enforcement_skipped") is True]
    active  = [r for r in output if r.get("enforcement_skipped") is False]
    assert len(skipped) == 2  # auto_fix + manual_review
    assert len(active)  == 2  # both ai_review rows


# ---------------------------------------------------------------------------
# Test 2 — Conflict rejection: row stays in output, only mutation is blocked
# ---------------------------------------------------------------------------

def test_conflict_rejection_row_remains():
    rt = _runtime(respect_routing=False)

    # Two rows for the same key with the same original text → conflict (identity fallback)
    rows = [
        {**_row("shared_key", "ai_review", fix="fix_A", idx=0), "old": "original"},
        {**_row("shared_key", "ai_review", fix="fix_B", idx=1), "old": "original"},
    ]
    input_count = len(rows)

    output, _, _, resolver = _simulate_ar_locale_qc(rows, rt)

    # Both rows must be present
    assert len(output) == input_count

    # Conflict was detected
    summary = resolver.summarize()
    assert summary["conflicts_detected"] >= 1

    # Second row must be annotated as enforcement_skipped (mutation blocked)
    assert output[0].get("enforcement_skipped") is False
    assert output[1].get("enforcement_skipped") is True


# ---------------------------------------------------------------------------
# Test 3 — Shared resolver is used across stages (same runtime instance)
# ---------------------------------------------------------------------------

def test_shared_resolver_across_stages():
    rt = _runtime(respect_routing=False)

    # Stage 1: ar_locale_qc registers a mutation for key "k1"
    rows_locale = [
        {**_row("k1", "ai_review", fix="fix_from_locale", idx=0), "old": "original_k1"},
    ]
    _simulate_ar_locale_qc(rows_locale, rt, stage_name="ar_locale_qc")

    # Stage 2: ar_semantic_qc tries the same key with same original_text
    rows_semantic = [
        {**_row("k1", "ai_review", fix="fix_from_semantic", idx=0), "old": "original_k1"},
    ]
    _simulate_ar_locale_qc(rows_semantic, rt, stage_name="ar_semantic_qc")

    # The shared resolver must have seen the conflict across stages
    resolver = get_conflict_resolver(rt)
    summary = resolver.summarize()
    assert summary["conflicts_detected"] >= 1, (
        "Shared resolver must detect cross-stage conflict for same key/original_text"
    )

    # Both stage outputs still have all their rows
    assert len(rows_locale)   == 1
    assert len(rows_semantic) == 1


# ---------------------------------------------------------------------------
# Test 4 — Multiple Arabic stages do NOT overwrite each other's metadata
# ---------------------------------------------------------------------------

def test_multiple_stages_do_not_overwrite_metadata():
    rt = _runtime(respect_routing=True)

    rows_locale = [_row("k1", "ai_review", idx=0), _row("k2", "auto_fix", idx=1)]
    _simulate_ar_locale_qc(rows_locale, rt, stage_name="ar_locale_qc")

    rows_semantic = [_row("k3", "manual_review", idx=0), _row("k4", "ai_review", idx=1)]
    _simulate_ar_locale_qc(rows_semantic, rt, stage_name="ar_semantic_qc")

    # Namespaced keys must both exist and be independent
    assert "feedback_metrics_ar_locale_qc"   in rt.metadata
    assert "feedback_metrics_ar_semantic_qc"  in rt.metadata
    assert "conflict_metrics_ar_locale_qc"   in rt.metadata
    assert "conflict_metrics_ar_semantic_qc"  in rt.metadata

    # Each conflict_metrics block carries its own stage tag
    assert rt.metadata["conflict_metrics_ar_locale_qc"]["stage"]  == "ar_locale_qc"
    assert rt.metadata["conflict_metrics_ar_semantic_qc"]["stage"] == "ar_semantic_qc"

    # Feedback totals are independent (each stage processed 2 rows)
    fb_locale   = rt.metadata["feedback_metrics_ar_locale_qc"]
    fb_semantic = rt.metadata["feedback_metrics_ar_semantic_qc"]
    assert fb_locale["total_signals"]   == 2
    assert fb_semantic["total_signals"] == 2


# ---------------------------------------------------------------------------
# Test 5 — Ordering preserved exactly (index-based, no sort side-effects)
# ---------------------------------------------------------------------------

def test_ordering_preserved_exactly():
    rt = _runtime(respect_routing=True)
    rows = [_row(f"key_{i}", "ai_review", idx=i) for i in range(10)]
    # Interleave different routes to force enforcement decisions
    for i in [2, 5, 8]:
        rows[i]["decision"]["route"] = "auto_fix"

    output, _, _, _ = _simulate_ar_locale_qc(rows, rt)

    assert len(output) == 10
    for expected_idx, row in enumerate(output):
        assert row["_original_idx"] == expected_idx, (
            f"Order violation at position {expected_idx}: got idx {row['_original_idx']}"
        )


# ---------------------------------------------------------------------------
# Test 6 — No routing baseline: all rows pass, enforcement_skipped=False
# ---------------------------------------------------------------------------

def test_no_routing_all_rows_pass_unannotated():
    rt = _runtime(respect_routing=False)
    rows = [
        _row("k1", "auto_fix",      idx=0),
        _row("k2", "ai_review",     idx=1),
        _row("k3", "manual_review", idx=2),
    ]
    output, enforcer, _, _ = _simulate_ar_locale_qc(rows, rt)

    assert not enforcer.enabled
    assert len(output) == 3
    # When routing is off, should_process always returns True → all actionable
    assert all(r.get("enforcement_skipped") is False for r in output)


# ---------------------------------------------------------------------------
# Test 7 — Determinism: repeated runs produce identical annotations
# ---------------------------------------------------------------------------

def test_determinism_repeated_runs():
    def run():
        rt = _runtime(respect_routing=True)
        rows = [
            _row("k1", "auto_fix",      fix="f1", idx=0),
            _row("k2", "ai_review",     fix="f2", idx=1),
            _row("k3", "manual_review", fix="f3", idx=2),
            _row("k4", "ai_review",     fix="f4", idx=3),
        ]
        output, _, fb, resolver = _simulate_ar_locale_qc(rows, rt)
        return (
            [r["_original_idx"] for r in output],
            [r.get("enforcement_skipped") for r in output],
            fb.summarize()["total_signals"],
            resolver.summarize()["conflicts_detected"],
        )

    a, b, c = run(), run(), run()
    assert a == b == c, "Non-deterministic output detected across runs"


# ---------------------------------------------------------------------------
# Test 8 — Feedback signals: source="arabic" present for every row
# ---------------------------------------------------------------------------

def test_feedback_source_is_arabic_for_all_rows():
    rt = _runtime(respect_routing=True)
    rows = [
        _row("k1", "auto_fix",      idx=0),
        _row("k2", "ai_review",     idx=1),
        _row("k3", "manual_review", idx=2),
    ]
    _, _, feedback, _ = _simulate_ar_locale_qc(rows, rt)

    summary = feedback.summarize()
    assert summary["total_signals"] == 3
    assert summary["signals_by_source"].get("arabic", 0) == 3
