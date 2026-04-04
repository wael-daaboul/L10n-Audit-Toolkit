"""
tests/test_project_memory.py
=============================
Phase 13 — Persistent Learning Profiles & Project Memory Tests.

Contract under test:
- Feature gate: disabled by default, enabled via config
- _resolve_project_id: priority chain (context_profile → hash(project_root) → default)
- _build_snapshot: pure function producing complete RunSnapshot
- _load_store / _save_store: atomic I/O with corruption recovery
- _build_learning_profile: deterministic aggregation from snapshots
- record_run_to_memory: end-to-end integration with sliding window
- Zero pipeline impact on failure (all exceptions swallowed)
- Determinism: same inputs → same LearningProfile across 3 runs
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict
from unittest.mock import patch

import pytest

from l10n_audit.core.project_memory import (
    LearningProfile,
    ProjectMemoryStore,
    RunSnapshot,
    _build_learning_profile,
    _build_snapshot,
    _load_store,
    _resolve_project_id,
    _save_store,
    record_run_to_memory,
)


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

@dataclass
class _Options:
    stage: str = "en_locale_qc"

    @dataclass
    class _Output:
        results_dir: str = "/tmp/test_l10n_results"

    output: _Output = field(default_factory=_Output)


@dataclass
class _Runtime:
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    context_profile: Any = None
    paths: Any = None


@dataclass
class _Issue:
    code: str = "spelling"
    locale: str = "en"
    source: str = "en_locale_qc"
    severity: str = "warning"
    fix_mode: str = "review_required"


def _rt_enabled(results_dir="/tmp/test_l10n_results", max_runs=500) -> _Runtime:
    return _Runtime(config={"project_memory": {"enabled": True, "max_runs": max_runs}})


def _rt_disabled() -> _Runtime:
    return _Runtime(config={"project_memory": {"enabled": False}})


def _rt_no_config() -> _Runtime:
    return _Runtime()


# ---------------------------------------------------------------------------
# Test 1 — Feature gate: disabled returns None immediately
# ---------------------------------------------------------------------------

def test_feature_gate_disabled_returns_none():
    rt = _rt_disabled()
    result = record_run_to_memory(rt, [_Issue()], _Options())
    assert result is None


def test_feature_gate_absent_returns_none():
    rt = _rt_no_config()
    result = record_run_to_memory(rt, [_Issue()], _Options())
    assert result is None


def test_feature_gate_enabled_returns_learning_profile(tmp_path):
    rt = _rt_enabled()
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))
    result = record_run_to_memory(rt, [_Issue()], opts)
    assert isinstance(result, LearningProfile)


# ---------------------------------------------------------------------------
# Test 2 — _resolve_project_id priority chain
# ---------------------------------------------------------------------------

def test_resolve_project_id_from_context_profile():
    from l10n_audit.core.context_profile import ContextProfile
    rt = _Runtime(context_profile=ContextProfile(project_id="my_proj", domain="legal"))
    assert _resolve_project_id(rt) == "my_proj"


def test_resolve_project_id_from_project_root():
    @dataclass
    class _Paths:
        project_root: str = "/some/project/root"

    rt = _Runtime(paths=_Paths())
    pid = _resolve_project_id(rt)
    assert pid.startswith("proj_")
    assert len(pid) == len("proj_") + 12


def test_resolve_project_id_fallback_to_default():
    rt = _Runtime()
    assert _resolve_project_id(rt) == "default_project"


def test_resolve_project_id_context_profile_wins_over_root():
    from l10n_audit.core.context_profile import ContextProfile

    @dataclass
    class _Paths:
        project_root: str = "/some/root"

    rt = _Runtime(
        context_profile=ContextProfile(project_id="explicit_id", domain="d"),
        paths=_Paths(),
    )
    assert _resolve_project_id(rt) == "explicit_id"


# ---------------------------------------------------------------------------
# Test 3 — _build_snapshot produces complete, valid RunSnapshot
# ---------------------------------------------------------------------------

def test_build_snapshot_fields():
    rt = _Runtime(config={"decision_engine": {"respect_routing": True}})
    issues = [_Issue(code="spelling", locale="en", source="en_locale_qc")] * 3
    snap = _build_snapshot(rt, issues, _Options(stage="en_locale_qc"))

    assert isinstance(snap, RunSnapshot)
    assert snap.total_issues == 3
    assert snap.stage == "en_locale_qc"
    assert snap.project_id == "default_project"
    assert snap.run_id != ""
    assert snap.timestamp > 0
    assert snap.routing_enabled is True
    assert "spelling" in snap.category_distribution


def test_build_snapshot_arabic_counting():
    issues = [
        _Issue(code="whitespace", locale="ar", source="ar_locale_qc"),
        _Issue(code="whitespace", locale="ar", source="ar_locale_qc"),
        _Issue(code="grammar", locale="en", source="en_locale_qc"),
    ]
    rt = _Runtime()
    snap = _build_snapshot(rt, issues, _Options())
    assert snap.arabic_findings == 2
    assert snap.english_findings == 1


def test_build_snapshot_context_metrics_from_metadata():
    rt = _Runtime(metadata={
        "context_routing_metrics": {
            "context_adjusted_count": 5,
            "context_downgrade_count": 3,
            "context_override_manual_count": 1,
            "by_route": {"auto_fix": 2, "ai_review": 4, "manual_review": 1},
        }
    })
    snap = _build_snapshot(rt, [], _Options())
    assert snap.context_adjusted_count == 5
    assert snap.context_downgrade_count == 3
    assert snap.context_override_manual_count == 1
    assert snap.auto_fix_count == 2
    assert snap.ai_review_count == 4
    assert snap.manual_review_count == 1


# ---------------------------------------------------------------------------
# Test 4 — _load_store / _save_store: round-trip and corruption recovery
# ---------------------------------------------------------------------------

def test_save_and_load_store_round_trip(tmp_path):
    path = str(tmp_path / "test_memory.json")
    store = ProjectMemoryStore(project_id="proj_abc", snapshots=[{"key": "value"}])
    _save_store(store, path)

    loaded = _load_store(path, "proj_abc")
    assert loaded.project_id == "proj_abc"
    assert len(loaded.snapshots) == 1
    assert loaded.snapshots[0]["key"] == "value"


def test_load_store_absent_file_returns_empty(tmp_path):
    path = str(tmp_path / "nonexistent.json")
    store = _load_store(path, "proj_xyz")
    assert store.project_id == "proj_xyz"
    assert store.snapshots == []


def test_load_store_corrupt_file_returns_empty(tmp_path):
    path = str(tmp_path / "corrupt.json")
    with open(path, "w") as fh:
        fh.write("{ this is not valid json !!!")
    store = _load_store(path, "proj_corrupt")
    assert store.snapshots == []


def test_save_store_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "deep" / "nested" / "memory.json")
    store = ProjectMemoryStore(project_id="p", snapshots=[])
    _save_store(store, path)
    assert os.path.isfile(path)


def test_save_store_is_atomic(tmp_path):
    """Verify no .tmp file survives after a successful write."""
    path = str(tmp_path / "atomic_memory.json")
    store = ProjectMemoryStore(project_id="p", snapshots=[{"x": 1}])
    _save_store(store, path)

    tmp_files = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert tmp_files == [], f"Leftover .tmp files: {tmp_files}"


# ---------------------------------------------------------------------------
# Test 5 — _build_learning_profile: aggregation correctness
# ---------------------------------------------------------------------------

def _snap_dict(**kwargs) -> dict:
    defaults = {
        "project_id": "p",
        "run_id": "r1",
        "timestamp": time.time(),
        "stage": "en_locale_qc",
        "version": "1.4.0",
        "total_issues": 10,
        "auto_fix_count": 5,
        "ai_review_count": 3,
        "manual_review_count": 2,
        "category_distribution": {"grammar": 6, "style": 4},
        "arabic_findings": 0,
        "english_findings": 10,
        "context_adjusted_count": 1,
        "context_downgrade_count": 0,
        "context_override_manual_count": 0,
        "calibration_active": False,
        "routing_enabled": True,
    }
    defaults.update(kwargs)
    return defaults


def test_build_learning_profile_empty_store():
    store = ProjectMemoryStore(project_id="p", snapshots=[])
    profile = _build_learning_profile(store)
    assert profile.run_count == 0
    assert profile.avg_total_issues == 0.0
    assert profile.dominant_category == ""


def test_build_learning_profile_single_run():
    store = ProjectMemoryStore(project_id="p", snapshots=[_snap_dict()])
    profile = _build_learning_profile(store)
    assert profile.run_count == 1
    assert profile.avg_total_issues == 10.0
    assert profile.avg_auto_fix_rate == 0.5   # 5/10
    assert profile.avg_ai_review_rate == 0.3  # 3/10
    assert profile.dominant_category == "grammar"
    assert profile.routing_enabled_runs == 1


def test_build_learning_profile_two_runs_averages():
    s1 = _snap_dict(total_issues=10, auto_fix_count=5, category_distribution={"grammar": 10})
    s2 = _snap_dict(total_issues=20, auto_fix_count=10, category_distribution={"style": 5, "grammar": 2})
    store = ProjectMemoryStore(project_id="p", snapshots=[s1, s2])
    profile = _build_learning_profile(store)
    assert profile.run_count == 2
    assert profile.avg_total_issues == 15.0
    # run1: 5/10=0.5, run2: 10/20=0.5 → avg=0.5
    assert profile.avg_auto_fix_rate == 0.5
    # grammar: 10+2=12, style: 5 → dominant is grammar
    assert profile.dominant_category == "grammar"


def test_build_learning_profile_arabic_run_count():
    s1 = _snap_dict(arabic_findings=0)
    s2 = _snap_dict(arabic_findings=3)
    s3 = _snap_dict(arabic_findings=0)
    store = ProjectMemoryStore(project_id="p", snapshots=[s1, s2, s3])
    profile = _build_learning_profile(store)
    assert profile.arabic_run_count == 1


def test_build_learning_profile_first_and_last_seen():
    t1, t2, t3 = 1000.0, 2000.0, 3000.0
    store = ProjectMemoryStore(project_id="p", snapshots=[
        _snap_dict(timestamp=t2),
        _snap_dict(timestamp=t1),  # out of insertion order
        _snap_dict(timestamp=t3),
    ])
    profile = _build_learning_profile(store)
    assert profile.first_seen == t1
    assert profile.last_seen == t3


# ---------------------------------------------------------------------------
# Test 6 — record_run_to_memory: sliding window enforcement
# ---------------------------------------------------------------------------

def test_sliding_window_evicts_oldest(tmp_path):
    rt = _Runtime(config={"project_memory": {"enabled": True, "max_runs": 3}})
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))
    issues = [_Issue()]

    # Record 5 runs with max_runs=3
    for _ in range(5):
        record_run_to_memory(rt, issues, opts, max_runs=3)

    # Read back the stored file
    pid = _resolve_project_id(rt)
    path = os.path.join(str(tmp_path), ".cache", "project_memory", f"{pid}_memory.json")
    with open(path) as fh:
        data = json.load(fh)

    assert len(data["snapshots"]) == 3, "Sliding window must enforce max_runs=3"


def test_sliding_window_uses_config_max_runs(tmp_path):
    rt = _Runtime(config={"project_memory": {"enabled": True, "max_runs": 2}})
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))
    issues = [_Issue()]

    for _ in range(10):
        record_run_to_memory(rt, issues, opts)

    pid = _resolve_project_id(rt)
    path = os.path.join(str(tmp_path), ".cache", "project_memory", f"{pid}_memory.json")
    with open(path) as fh:
        data = json.load(fh)

    assert len(data["snapshots"]) == 2


# ---------------------------------------------------------------------------
# Test 7 — Determinism: 3 independent runs → identical LearningProfile fields
# ---------------------------------------------------------------------------

def test_determinism_three_runs(tmp_path):
    """Same snapshot data → same LearningProfile every time."""
    store = ProjectMemoryStore(project_id="p", snapshots=[
        _snap_dict(total_issues=10, auto_fix_count=5, category_distribution={"grammar": 6}),
        _snap_dict(total_issues=20, auto_fix_count=8, category_distribution={"style": 10}),
        _snap_dict(total_issues=15, arabic_findings=4, category_distribution={"grammar": 3}),
    ])
    profiles = [_build_learning_profile(store) for _ in range(3)]

    ref = profiles[0]
    for p in profiles[1:]:
        assert p.run_count == ref.run_count
        assert p.avg_total_issues == ref.avg_total_issues
        assert p.avg_auto_fix_rate == ref.avg_auto_fix_rate
        assert p.dominant_category == ref.dominant_category
        assert p.arabic_run_count == ref.arabic_run_count


# ---------------------------------------------------------------------------
# Test 8 — Zero pipeline impact: exceptions swallowed, returns None
# ---------------------------------------------------------------------------

def test_exception_in_save_returns_none_not_raised(tmp_path):
    rt = _rt_enabled(results_dir=str(tmp_path))
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))

    with patch("l10n_audit.core.project_memory._save_store", side_effect=OSError("disk full")):
        result = record_run_to_memory(rt, [_Issue()], opts)

    assert result is None  # failure swallowed, no exception propagated


def test_corrupt_runtime_config_returns_none():
    """If runtime.config is not a dict, no exception must escape."""
    @dataclass
    class _BadRuntime:
        config: Any = "not_a_dict"
        metadata: dict = field(default_factory=dict)

    result = record_run_to_memory(_BadRuntime(), [_Issue()], _Options())
    assert result is None


# ---------------------------------------------------------------------------
# Test 9 — Accumulation: run_count grows with each call
# ---------------------------------------------------------------------------

def test_run_count_accumulates(tmp_path):
    rt = _rt_enabled()
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))

    p1 = record_run_to_memory(rt, [_Issue()], opts)
    p2 = record_run_to_memory(rt, [_Issue(), _Issue()], opts)
    p3 = record_run_to_memory(rt, [], opts)

    assert p1.run_count == 1
    assert p2.run_count == 2
    assert p3.run_count == 3


# ---------------------------------------------------------------------------
# Test 10 — Storage path structure
# ---------------------------------------------------------------------------

def test_storage_path_structure(tmp_path):
    rt = _rt_enabled()
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))

    record_run_to_memory(rt, [_Issue()], opts)

    cache_dir = tmp_path / ".cache" / "project_memory"
    assert cache_dir.is_dir()
    json_files = list(cache_dir.glob("*_memory.json"))
    assert len(json_files) == 1


# ---------------------------------------------------------------------------
# Test 11 — calibration_active derivation correctness (Phase 13 bug fix)
# ---------------------------------------------------------------------------

def test_calibration_active_true_when_enabled_true():
    """Case 1: calibration.enabled = True → calibration_active must be True."""
    rt = _Runtime(config={"calibration": {"enabled": True}})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is True


def test_calibration_active_false_when_enabled_false():
    """Case 2: calibration.enabled = False → calibration_active must be False."""
    rt = _Runtime(config={"calibration": {"enabled": False}})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_false_when_enabled_absent():
    """Case 3: calibration dict present but enabled key absent → False."""
    rt = _Runtime(config={"calibration": {}})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_false_when_calibration_absent():
    """Case 4: calibration key absent from config entirely → False."""
    rt = _Runtime(config={})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_false_when_calibration_is_none():
    """Case 5: calibration key exists but is None (not a dict) → False."""
    rt = _Runtime(config={"calibration": None})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_false_when_config_absent():
    """Case 4b: runtime.config is entirely absent → False."""
    rt = _Runtime()   # config = {} (default_factory=dict, so no calibration key)
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_false_when_calibration_is_non_dict():
    """calibration value is a non-dict truthy type (e.g. string) → False."""
    rt = _Runtime(config={"calibration": "yes"})
    snap = _build_snapshot(rt, [], _Options())
    assert snap.calibration_active is False


def test_calibration_active_runs_reflects_corrected_count():
    """Case 6: calibration_active_runs in LearningProfile counts correctly
    after the fix. Only snapshots with calibration_active=True are counted."""
    store = ProjectMemoryStore(project_id="p", snapshots=[
        _snap_dict(calibration_active=True),
        _snap_dict(calibration_active=False),
        _snap_dict(calibration_active=True),
        _snap_dict(calibration_active=True),
        _snap_dict(calibration_active=False),
    ])
    profile = _build_learning_profile(store)
    assert profile.calibration_active_runs == 3


def test_calibration_active_runs_zero_when_none_active():
    """calibration_active_runs = 0 when no snapshot has calibration_active=True."""
    store = ProjectMemoryStore(project_id="p", snapshots=[
        _snap_dict(calibration_active=False),
        _snap_dict(calibration_active=False),
    ])
    profile = _build_learning_profile(store)
    assert profile.calibration_active_runs == 0


def test_calibration_active_enabled_false_does_not_contaminate_count(tmp_path):
    """End-to-end: config with calibration.enabled=False must not increment
    calibration_active_runs across multiple recorded runs."""
    rt = _Runtime(config={
        "project_memory": {"enabled": True, "max_runs": 500},
        "calibration": {"enabled": False},
    })
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))

    for _ in range(3):
        record_run_to_memory(rt, [_Issue()], opts)

    # Read the stored file directly to verify raw snapshot values.
    pid = _resolve_project_id(rt)
    import os
    path = os.path.join(str(tmp_path), ".cache", "project_memory", f"{pid}_memory.json")
    with open(path) as fh:
        import json as _json
        data = _json.load(fh)

    for snap in data["snapshots"]:
        assert snap["calibration_active"] is False, (
            "calibration_active must be False when calibration.enabled=False"
        )


def test_calibration_active_enabled_true_increments_count(tmp_path):
    """End-to-end: config with calibration.enabled=True must set
    calibration_active=True in every snapshot and reflect in profile."""
    rt = _Runtime(config={
        "project_memory": {"enabled": True, "max_runs": 500},
        "calibration": {"enabled": True},
    })
    opts = _Options(output=_Options._Output(results_dir=str(tmp_path)))

    for _ in range(3):
        profile = record_run_to_memory(rt, [_Issue()], opts)

    assert profile is not None
    assert profile.calibration_active_runs == 3
