"""
l10n_audit/core/project_memory.py
==================================
Phase 13 — Persistent Learning Profiles & Project Memory.

Design constraints
------------------
* Feature-gated: disabled by default; opt-in via runtime.config["project_memory"]["enabled"].
* Zero pipeline impact on failure — all I/O wrapped in try/except.
* Atomic file writes via .tmp + os.replace().
* Deterministic: same snapshots → same LearningProfile every time.
* Pure aggregation functions — no side effects except record_run_to_memory().
* Sliding window: max_runs cap (default 500) — oldest snapshots evicted first.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("l10n_audit.project_memory")

_MEMORY_VERSION = "1.0"
# Upper bound for the sliding window when not configured via config.
# The config default exposed to users is 50 (see config.example.json).
# This higher fallback is intentional — only reached if max_runs is absent
# from config entirely, meaning the user opted in without specifying a cap.
_DEFAULT_MAX_RUNS = 500


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class RunSnapshot:
    """Immutable record of a single completed audit run.

    All fields are serialisable to JSON without loss of precision.
    """
    project_id: str
    run_id: str                          # ISO-8601 timestamp + 6-char hex suffix
    timestamp: float                     # Unix epoch seconds (time.time())
    stage: str                           # options.stage value
    version: str                         # l10n_audit.__version__
    total_issues: int
    auto_fix_count: int
    ai_review_count: int
    manual_review_count: int
    category_distribution: Dict[str, int] = field(default_factory=dict)
    arabic_findings: int = 0
    english_findings: int = 0
    context_adjusted_count: int = 0
    context_downgrade_count: int = 0
    context_override_manual_count: int = 0
    calibration_active: bool = False
    routing_enabled: bool = False


@dataclass
class ProjectMemoryStore:
    """Persistent store for a single project's run history.

    Serialised as JSON to disk; loaded atomically on each record call.
    """
    project_id: str
    memory_version: str = _MEMORY_VERSION
    snapshots: List[Dict[str, Any]] = field(default_factory=list)  # raw dicts for JSON round-trip


@dataclass
class LearningProfile:
    """Aggregated intelligence distilled from a project's run history.

    Computed on-the-fly from ProjectMemoryStore — never stored on disk.
    All numeric fields are rounded to 4 decimal places for determinism.
    """
    project_id: str
    run_count: int
    avg_total_issues: float
    avg_auto_fix_rate: float        # auto_fix_count / total_issues per run, averaged
    avg_ai_review_rate: float
    avg_manual_review_rate: float
    avg_context_adjusted_rate: float
    dominant_category: str          # category with highest cumulative count
    arabic_run_count: int           # runs that produced >= 1 arabic finding
    calibration_active_runs: int
    routing_enabled_runs: int
    first_seen: float               # timestamp of oldest snapshot
    last_seen: float                # timestamp of newest snapshot


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_project_id(runtime: Any) -> str:
    """Determine project_id with fallback chain.

    Priority:
    1. runtime.context_profile.project_id
    2. sha256(project_root)[:12]
    3. "default_project"
    """
    try:
        cp = getattr(runtime, "context_profile", None)
        if cp is not None:
            pid = getattr(cp, "project_id", None)
            if pid:
                return str(pid)
    except Exception:
        pass

    try:
        paths = getattr(runtime, "paths", None) or runtime
        project_root = str(getattr(paths, "project_root", "") or "")
        if project_root:
            digest = hashlib.sha256(project_root.encode()).hexdigest()[:12]
            return f"proj_{digest}"
    except Exception:
        pass

    return "default_project"


def _build_snapshot(runtime: Any, issues: list, options: Any) -> RunSnapshot:
    """Build a RunSnapshot from the completed run state. Pure function."""
    from l10n_audit import __version__

    project_id = _resolve_project_id(runtime)

    # Stable run_id: timestamp prefix + 6-char hash of project+stage
    ts = time.time()
    ts_str = str(int(ts))
    stage = getattr(options, "stage", "unknown") or "unknown"
    suffix = hashlib.sha256(f"{project_id}{stage}{ts_str}".encode()).hexdigest()[:6]
    run_id = f"{ts_str}_{suffix}"

    # Category distribution from AuditIssue.code
    cat_dist: Dict[str, int] = {}
    arabic_count = 0
    english_count = 0
    for issue in issues:
        code = getattr(issue, "code", None) or getattr(issue, "issue_type", "unknown")
        cat_dist[code] = cat_dist.get(code, 0) + 1
        locale = str(getattr(issue, "locale", "") or "").lower()
        source = str(getattr(issue, "source", "") or "").lower()
        if "ar" in locale or "arabic" in source or "ar_" in source:
            arabic_count += 1
        else:
            english_count += 1

    # Route queue sizes from routing_metrics metadata (Phase 12)
    metadata = getattr(runtime, "metadata", {}) or {}
    ctx_metrics = metadata.get("context_routing_metrics", {}) or {}
    auto_fix = ctx_metrics.get("by_route", {}).get("auto_fix", 0)
    ai_review = ctx_metrics.get("by_route", {}).get("ai_review", 0)
    manual_review = ctx_metrics.get("by_route", {}).get("manual_review", 0)

    # Fallback: count by issue severity/route if routing_metrics absent
    if auto_fix == 0 and ai_review == 0 and manual_review == 0:
        for issue in issues:
            sev = str(getattr(issue, "severity", "") or "").lower()
            route_hint = str(getattr(issue, "fix_mode", "") or "").lower()
            if "auto" in route_hint:
                auto_fix += 1
            elif "review" in route_hint:
                ai_review += 1
            else:
                manual_review += 1

    _cal_cfg = (getattr(runtime, "config", {}) or {}).get("calibration")
    calibration_active = bool(
        isinstance(_cal_cfg, dict) and _cal_cfg.get("enabled", False)
    )
    routing_enabled = bool(
        ((getattr(runtime, "config", {}) or {}).get("decision_engine", {})).get("respect_routing", False)
    )

    return RunSnapshot(
        project_id=project_id,
        run_id=run_id,
        timestamp=ts,
        stage=stage,
        version=__version__,
        total_issues=len(issues),
        auto_fix_count=auto_fix,
        ai_review_count=ai_review,
        manual_review_count=manual_review,
        category_distribution=cat_dist,
        arabic_findings=arabic_count,
        english_findings=english_count,
        context_adjusted_count=ctx_metrics.get("context_adjusted_count", 0),
        context_downgrade_count=ctx_metrics.get("context_downgrade_count", 0),
        context_override_manual_count=ctx_metrics.get("context_override_manual_count", 0),
        calibration_active=calibration_active,
        routing_enabled=routing_enabled,
    )


def _store_path(runtime: Any, options: Any, project_id: str) -> str:
    """Return the absolute path for this project's memory JSON file."""
    try:
        results_dir = str(getattr(options, "output", None) and getattr(options.output, "results_dir", "") or "")
    except Exception:
        results_dir = ""

    if not results_dir:
        results_dir = ".l10n-audit/Results"

    cache_dir = os.path.join(results_dir, ".cache", "project_memory")
    return os.path.join(cache_dir, f"{project_id}_memory.json")


def _load_store(path: str, project_id: str) -> ProjectMemoryStore:
    """Load ProjectMemoryStore from disk. Returns empty store on any error."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("root is not a dict")
        snapshots = raw.get("snapshots", [])
        if not isinstance(snapshots, list):
            snapshots = []
        return ProjectMemoryStore(
            project_id=raw.get("project_id", project_id),
            memory_version=raw.get("memory_version", _MEMORY_VERSION),
            snapshots=snapshots,
        )
    except FileNotFoundError:
        return ProjectMemoryStore(project_id=project_id)
    except Exception as exc:
        logger.warning("project_memory: corrupt store at %s (%s) — starting fresh", path, exc)
        return ProjectMemoryStore(project_id=project_id)


def _save_store(store: ProjectMemoryStore, path: str) -> None:
    """Atomically write store to path via .tmp + os.replace()."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "project_id": store.project_id,
        "memory_version": store.memory_version,
        "snapshots": store.snapshots,
    }
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _build_learning_profile(store: ProjectMemoryStore) -> LearningProfile:
    """Aggregate stored snapshots into a LearningProfile. Pure, deterministic."""
    snaps = store.snapshots
    n = len(snaps)

    if n == 0:
        return LearningProfile(
            project_id=store.project_id,
            run_count=0,
            avg_total_issues=0.0,
            avg_auto_fix_rate=0.0,
            avg_ai_review_rate=0.0,
            avg_manual_review_rate=0.0,
            avg_context_adjusted_rate=0.0,
            dominant_category="",
            arabic_run_count=0,
            calibration_active_runs=0,
            routing_enabled_runs=0,
            first_seen=0.0,
            last_seen=0.0,
        )

    total_issues_sum = 0.0
    auto_fix_rate_sum = 0.0
    ai_review_rate_sum = 0.0
    manual_review_rate_sum = 0.0
    ctx_adj_rate_sum = 0.0
    arabic_runs = 0
    cal_runs = 0
    routing_runs = 0
    cat_totals: Dict[str, int] = {}
    timestamps: List[float] = []

    for s in snaps:
        total = s.get("total_issues", 0) or 0
        total_issues_sum += total
        denom = max(1, total)

        auto_fix_rate_sum += s.get("auto_fix_count", 0) / denom
        ai_review_rate_sum += s.get("ai_review_count", 0) / denom
        manual_review_rate_sum += s.get("manual_review_count", 0) / denom
        ctx_adj_rate_sum += s.get("context_adjusted_count", 0) / denom

        if s.get("arabic_findings", 0) > 0:
            arabic_runs += 1
        if s.get("calibration_active", False):
            cal_runs += 1
        if s.get("routing_enabled", False):
            routing_runs += 1

        for cat, cnt in (s.get("category_distribution") or {}).items():
            cat_totals[cat] = cat_totals.get(cat, 0) + cnt

        ts = s.get("timestamp", 0.0)
        if ts:
            timestamps.append(ts)

    dominant = max(cat_totals, key=lambda k: cat_totals[k]) if cat_totals else ""
    timestamps_sorted = sorted(timestamps)

    def _r(v: float) -> float:
        return round(v / n, 4)

    return LearningProfile(
        project_id=store.project_id,
        run_count=n,
        avg_total_issues=round(total_issues_sum / n, 4),
        avg_auto_fix_rate=_r(auto_fix_rate_sum),
        avg_ai_review_rate=_r(ai_review_rate_sum),
        avg_manual_review_rate=_r(manual_review_rate_sum),
        avg_context_adjusted_rate=_r(ctx_adj_rate_sum),
        dominant_category=dominant,
        arabic_run_count=arabic_runs,
        calibration_active_runs=cal_runs,
        routing_enabled_runs=routing_runs,
        first_seen=timestamps_sorted[0] if timestamps_sorted else 0.0,
        last_seen=timestamps_sorted[-1] if timestamps_sorted else 0.0,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def record_run_to_memory(
    runtime: Any,
    issues: list,
    options: Any,
    *,
    max_runs: int = _DEFAULT_MAX_RUNS,
) -> Optional[LearningProfile]:
    """Record this run's snapshot to project memory and return the updated LearningProfile.

    Feature-gated: returns None immediately when project_memory.enabled is falsy.
    All exceptions are caught and logged — never propagated to the caller.

    Parameters
    ----------
    runtime:
        The active runtime object (AuditPaths or similar). Must have .config dict.
    issues:
        The list of AuditIssue instances returned by the pipeline.
    options:
        The AuditOptions for this run (provides stage, output.results_dir).
    max_runs:
        Sliding window size. Oldest snapshots are evicted when exceeded.

    Returns
    -------
    LearningProfile if memory is enabled and recording succeeded, else None.
    """
    try:
        config = getattr(runtime, "config", {}) or {}
        pm_config = config.get("project_memory", {}) or {}
        if not pm_config.get("enabled", False):
            return None

        effective_max = int(pm_config.get("max_runs", max_runs))

        project_id = _resolve_project_id(runtime)
        path = _store_path(runtime, options, project_id)

        store = _load_store(path, project_id)
        snapshot = _build_snapshot(runtime, issues, options)
        store.snapshots.append(asdict(snapshot))

        # Enforce sliding window
        if len(store.snapshots) > effective_max:
            store.snapshots = store.snapshots[-effective_max:]

        _save_store(store, path)

        profile = _build_learning_profile(store)
        logger.info(
            "project_memory: recorded run %s for project %s (%d total runs stored)",
            snapshot.run_id, project_id, len(store.snapshots),
        )
        return profile

    except Exception as exc:
        logger.warning("project_memory: failed to record run (%s) — pipeline unaffected", exc)
        return None
