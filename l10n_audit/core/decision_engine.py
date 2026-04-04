"""
l10n_audit/core/decision_engine.py
==================================
Phase 1: Passive Decision Layer (Shadow Mode).
Evaluates rules and assigns findings to queues, but enforces zero behavior change downstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from l10n_audit.core.languagetool_layer import LTFinding


def is_routing_enabled(runtime: Any) -> bool:
    """Check if the Decision Engine routing should be respected downstream.
    
    Defaults to False to guarantee zero behavior change unless explicitly enabled
    in the runtime configuration.
    """
    try:
        config = getattr(runtime, "config", {})
        if not isinstance(config, dict):
            return False
        decision_config = config.get("decision_engine", {})
        if not isinstance(decision_config, dict):
            return False
        return bool(decision_config.get("respect_routing", False))
    except Exception:
        return False


class RouteAction(str, Enum):
    AUTO_FIX = "auto_fix"
    AI_REVIEW = "ai_review"
    MANUAL_REVIEW = "manual_review"
    DROPPED = "dropped"


class DecisionRule(Protocol):
    def __call__(self, finding: LTFinding, ctx: DecisionContext) -> Optional[RouteAction]:
        ...


@dataclass
class DecisionContext:
    findings: list[LTFinding]
    source: str  # "en" | "ar"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionResult:
    auto_fix: list[LTFinding] = field(default_factory=list)
    ai_review: list[LTFinding] = field(default_factory=list)
    manual_review: list[LTFinding] = field(default_factory=list)
    dropped: list[LTFinding] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scoring Engine (Phase 7)
# ---------------------------------------------------------------------------

def score_finding(finding: LTFinding, ctx: DecisionContext) -> dict:
    """Evaluate finding context to determine deterministic risk and confidence levels."""
    confidence = 0.5
    risk = "low"

    if finding.is_simple_fix:
        confidence += 0.3

    if getattr(finding, "suggested_text", "") == "":
        confidence -= 0.4
        risk = "high"

    category = getattr(finding, "issue_category", "").lower()
    if category == "grammar":
        confidence += 0.2
    elif category == "style":
        confidence += 0.1

    return {
        "confidence": max(0.0, min(1.0, confidence)),
        "risk": risk
    }


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------

def evaluate_findings(ctx: DecisionContext, runtime: object = None) -> DecisionResult:
    """Evaluate a batch of findings using adaptive scoring logic.

    Phase 9: Added calibration support. If calibration is enabled in runtime config,
    thresholds are adjusted based on Phase 8 feedback signals before finalizing routes.
    Phase 12: Added context-aware adjustment layer (after scoring + calibration).
    """
    from l10n_audit.core.calibration_engine import CalibrationEngine
    from l10n_audit.core.context_profile import get_context_profile, apply_context_rules
    from l10n_audit.core.routing_metrics import RoutingMetrics

    result = DecisionResult()

    # --- Phase 9: Setup Calibration (Post-Scoring Layer) ---
    cal_engine = CalibrationEngine.from_runtime(runtime)
    profiles = None
    if cal_engine is not None:
        try:
            # Build profiles from observed feedback (Phase 8 signals)
            feedback = getattr(runtime, "metadata", {}).get("feedback_metrics", {})
            profiles = cal_engine.build_profiles(feedback)
            # Store analytical summary of calibration state
            cal_engine.store_calibration_metrics(runtime, profiles)
        except Exception:
            profiles = None  # robust fallback to defaults if metrics are corrupt

    # --- Phase 12: Setup Context Profile (optional, flag-gated via runtime attribute) ---
    context_profile = get_context_profile(runtime)
    context_metrics = RoutingMetrics()  # collects Phase 12 counters independently

    for finding in ctx.findings:
        # Step 1: Base Scoring (Deterministic Heuristics) — untouched
        score = score_finding(finding, ctx)
        finding.confidence_score = score["confidence"]
        finding.risk_level = score["risk"]

        # Step 2: Base Route Assignment (Phase 7 Thresholds)
        if score["confidence"] >= 0.8 and finding.is_simple_fix:
            assigned_route = RouteAction.AUTO_FIX
        elif score["confidence"] <= 0.3:
            assigned_route = RouteAction.MANUAL_REVIEW
        else:
            assigned_route = RouteAction.AI_REVIEW

        # Step 3: Phase 9 Calibration (Post-Processing Override)
        if profiles is not None:
            assigned_route = cal_engine.calibrate_route(
                assigned_route,
                finding.confidence_score,
                finding.is_simple_fix,
                profiles
            )

        # Step 4: Phase 12 Context Adjustment (after scoring + calibration, before queue commit)
        context_adj = None
        if context_profile is not None:
            assigned_route, context_adj = apply_context_rules(
                finding, assigned_route, context_profile
            )
            context_metrics.record_context_adjustment(context_adj.rules_triggered)

        # Attach context decision payload to finding for downstream observability
        finding._context_adjustment = context_adj

        # Assign to correct queue
        if assigned_route == RouteAction.AUTO_FIX:
            result.auto_fix.append(finding)
        elif assigned_route == RouteAction.AI_REVIEW:
            result.ai_review.append(finding)
        elif assigned_route == RouteAction.MANUAL_REVIEW:
            result.manual_review.append(finding)
        elif assigned_route == RouteAction.DROPPED:
            result.dropped.append(finding)

    # Persist Phase 12 context metrics to runtime when a profile is active
    if context_profile is not None and hasattr(runtime, "metadata"):
        runtime.metadata["context_routing_metrics"] = context_metrics.to_dict()

    return result


def apply_arabic_decision_routing(rows: list[dict], suggestion_key: str = "new", runtime: object = None) -> None:
    """Inject decision metadata into a batch of Arabic findings (Phase 4 Prep).

    Evaluates Arabic findings using existing rules, injects {"decision": {"route": ...}},
    and logs metrics without enforcing skips or drops, preserving len(rows).

    Phase 12: accepts optional runtime so context profile annotations propagate to
    Arabic rows as metadata-only (annotation only — no route behavior changes).
    """
    from l10n_audit.core.routing_metrics import RoutingMetrics
    from l10n_audit.core.context_profile import get_context_profile
    import logging

    if not rows:
        return

    logger = logging.getLogger("l10n_audit.ar_routing")
    metrics = RoutingMetrics()
    context_profile = get_context_profile(runtime)

    findings_to_evaluate = []
    for row in rows:
        f = LTFinding(
            key=row.get("key", ""),
            rule_id=row.get("issue_type", ""),
            issue_category=row.get("issue_type", ""),
            message=row.get("message", ""),
            original_text=row.get("old", ""),
            suggested_text=row.get(suggestion_key, ""),
            offset=0,
            error_length=0,
            is_simple_fix=(row.get("fix_mode") == "auto_safe")
        )
        f._original_row_index = len(findings_to_evaluate)
        findings_to_evaluate.append(f)

    ctx = DecisionContext(findings=findings_to_evaluate, source="ar")
    result = evaluate_findings(ctx, runtime)

    routes_by_index = ["ai_review"] * len(findings_to_evaluate)

    for f in result.auto_fix:
        routes_by_index[f._original_row_index] = "auto_fix"

    for f in result.manual_review:
        routes_by_index[f._original_row_index] = "manual_review"

    for f in result.dropped:
        routes_by_index[f._original_row_index] = "dropped"

    for i, row in enumerate(rows):
        finding = findings_to_evaluate[i]
        route = routes_by_index[i]

        # Build context annotation from finding._context_adjustment (Phase 12).
        # Arabic is annotation-only: context fields are attached but route is
        # determined purely by scoring/calibration — no context rule override.
        ctx_adj = getattr(finding, "_context_adjustment", None)
        context_applied = ctx_adj.context_applied if ctx_adj is not None else False
        context_rules = ctx_adj.rules_triggered if ctx_adj is not None else []

        row["decision"] = {
            "route": route,
            "confidence": round(finding.confidence_score, 2),
            "risk": finding.risk_level,
            "engine_version": "v3",
            "context_applied": context_applied,
            "context_rules_triggered": context_rules,
        }
        metrics.record(route)
        if hasattr(metrics, "record_adaptive"):
            metrics.record_adaptive(finding.confidence_score, finding.risk_level)

    import json
    logger.info("Routing Metrics [arabic_pipeline]: %s", json.dumps(metrics.to_dict()))
