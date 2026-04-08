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


DECISION_EXPLANATION_CODES: tuple[str, ...] = (
    "simple_fix_bonus",
    "missing_suggestion_penalty",
    "grammar_signal",
    "style_signal",
    "meaning_loss_high_penalty",
    "meaning_loss_medium_penalty",
    "semantic_shape_mismatch_penalty",
    "semantic_action_loss_penalty",
    "semantic_entity_mismatch_penalty",
    "placeholder_mismatch_penalty",
    "placeholder_missing_penalty",
    "glossary_alignment_bonus",
    "glossary_drift_penalty",
    "glossary_violation_penalty",
    "structural_consistency_bonus",
    "structural_shape_mismatch_penalty",
    "structural_collision_penalty",
    "feedback_autofix_acceptance_bonus",
    "feedback_autofix_rejection_penalty",
    "feedback_ai_review_acceptance_bonus",
    "feedback_manual_review_caution_penalty",
    "feedback_meaning_loss_caution_penalty",
    "feedback_grammar_acceptance_bonus",
    "feedback_style_caution_penalty",
    "feedback_placeholder_rejection_penalty",
    "feedback_glossary_acceptance_bonus",
    "feedback_structural_caution_penalty",
    "cross_evidence_meaning_loss_placeholder_penalty",
    "cross_evidence_structural_low_confidence_penalty",
    "cross_evidence_glossary_meaning_penalty",
    "domain_low_tolerance_penalty",
    "domain_high_tolerance_bonus",
    "profile_low_risk_tolerance_penalty",
    "profile_style_strictness_penalty",
    "profile_glossary_enforced_caution",
    "profile_manual_preference_caution",
    "style_penalty",
    "risk_downgrade",
    "manual_override",
    "calibration_downgrade",
)


# ---------------------------------------------------------------------------
# Scoring Engine (Phase 7)
# ---------------------------------------------------------------------------

def _read_scalar_evidence(
    finding: LTFinding,
    ctx: DecisionContext,
    attr_name: str,
    metadata_key: str,
) -> str:
    """Read simple scalar evidence from finding first, then ctx metadata by key."""
    finding_value = getattr(finding, attr_name, "")
    if isinstance(finding_value, str) and finding_value.strip():
        return finding_value.strip().lower()
    metadata_map = ctx.metadata.get(metadata_key, {})
    if isinstance(metadata_map, dict):
        metadata_value = metadata_map.get(getattr(finding, "key", ""), "")
        if isinstance(metadata_value, str) and metadata_value.strip():
            return metadata_value.strip().lower()
    return ""


def _read_feedback_metrics(ctx: DecisionContext) -> dict[str, dict[str, float]]:
    """Read feedback metrics from ctx metadata without mutating any state."""
    feedback = ctx.metadata.get("feedback_metrics", {})
    if not isinstance(feedback, dict):
        feedback = {}

    def read_metric(name: str) -> dict[str, float]:
        metric_map = feedback.get(name, ctx.metadata.get(name, {}))
        if not isinstance(metric_map, dict):
            return {}
        cleaned: dict[str, float] = {}
        for key, value in metric_map.items():
            try:
                cleaned[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return cleaned

    return {
        "acceptance_rate_by_route": read_metric("acceptance_rate_by_route"),
        "rejection_rate_by_route": read_metric("rejection_rate_by_route"),
        "avg_confidence_by_route": read_metric("avg_confidence_by_route"),
        "acceptance_rate_by_issue_family": read_metric("acceptance_rate_by_issue_family"),
        "rejection_rate_by_issue_family": read_metric("rejection_rate_by_issue_family"),
        "avg_confidence_by_issue_family": read_metric("avg_confidence_by_issue_family"),
    }


def _route_from_confidence(confidence: float, is_simple_fix: bool) -> str:
    """Project the current route from confidence using existing thresholds."""
    if confidence >= 0.8 and is_simple_fix:
        return RouteAction.AUTO_FIX.value
    if confidence <= 0.3:
        return RouteAction.MANUAL_REVIEW.value
    return RouteAction.AI_REVIEW.value


def _read_domain(ctx: DecisionContext) -> str:
    """Read domain from existing context metadata only."""
    direct_domain = ctx.metadata.get("domain", ctx.metadata.get("context_domain", ""))
    if isinstance(direct_domain, str) and direct_domain.strip():
        return direct_domain.strip().lower()
    context_profile = ctx.metadata.get("context_profile")
    if isinstance(context_profile, dict):
        profile_domain = context_profile.get("domain", "")
        if isinstance(profile_domain, str) and profile_domain.strip():
            return profile_domain.strip().lower()
    return ""


def _read_context_profile_metadata(ctx: DecisionContext) -> dict[str, object]:
    """Read a minimal context profile shape from ctx metadata without mutation."""
    raw_profile = ctx.metadata.get("context_profile", {})
    if raw_profile is None:
        return {}

    def _get(raw: object, name: str, default: object) -> object:
        if isinstance(raw, dict):
            return raw.get(name, default)
        return getattr(raw, name, default)

    profile: dict[str, object] = {}
    domain = _get(raw_profile, "domain", "")
    if isinstance(domain, str) and domain.strip():
        profile["domain"] = domain.strip().lower()

    risk_tolerance = _get(raw_profile, "risk_tolerance", "")
    if isinstance(risk_tolerance, str) and risk_tolerance.strip():
        profile["risk_tolerance"] = risk_tolerance.strip().lower()

    style_strictness = _get(raw_profile, "style_strictness", None)
    try:
        if style_strictness is not None:
            profile["style_strictness"] = float(style_strictness)
    except (TypeError, ValueError):
        pass

    prefer_manual_review = _get(raw_profile, "prefer_manual_review", None)
    if isinstance(prefer_manual_review, bool):
        profile["prefer_manual_review"] = prefer_manual_review

    glossary_enforced = _get(raw_profile, "glossary_enforced", None)
    if isinstance(glossary_enforced, bool):
        profile["glossary_enforced"] = glossary_enforced

    return profile


def _build_confidence_feedback_sources(contributions: list[dict[str, object]]) -> list[dict[str, object]]:
    """Extract additive feedback-like adjustments for explainability."""
    feedback_like_sources = {"feedback_weighting", "cross_evidence", "domain_weighting", "context_profile_weighting"}
    return [
        {
            "source": str(contribution["source"]),
            "delta": float(contribution["delta"]),
            "reason": str(contribution["code"]),
        }
        for contribution in contributions
        if str(contribution["source"]) in feedback_like_sources
    ]


def _build_context_profile_signals(contributions: list[dict[str, object]]) -> list[dict[str, object]]:
    """Extract profile-specific adjustments for explainability."""
    return [
        {
            "source": str(contribution["source"]),
            "delta": float(contribution["delta"]),
            "reason": str(contribution["code"]),
        }
        for contribution in contributions
        if str(contribution["source"]) == "context_profile_weighting"
    ]


def _infer_issue_family(
    finding: LTFinding,
    ctx: DecisionContext,
    semantic_risk: str,
    placeholder_integrity: str,
    glossary_alignment: str,
    structural_consistency: str,
) -> str:
    """Infer a finite issue family for feedback weighting."""
    if semantic_risk in {"medium", "high"}:
        return "meaning_loss"
    if placeholder_integrity in {"mismatch", "missing"}:
        return "placeholder"
    if glossary_alignment in {"approved", "drift", "violation"}:
        return "glossary"
    if structural_consistency in {"ok", "shape_mismatch", "nested_collision"}:
        return "structural"

    category = str(getattr(finding, "issue_category", "")).strip().lower()
    if category == "grammar":
        return "grammar"
    if category == "style":
        return "style"
    return "generic"

def _build_evidence_contributions(finding: LTFinding, ctx: DecisionContext) -> tuple[list[dict[str, object]], str, str]:
    """Build deterministic confidence contributions from finding evidence."""
    contributions: list[dict[str, object]] = []
    risk = "low"

    def add(code: str, delta: float, source: str) -> None:
        nonlocal risk
        contributions.append(
            {
                "code": code,
                "delta": delta,
                "kind": "bonus" if delta >= 0 else "penalty",
                "source": source,
            }
        )

    if finding.is_simple_fix:
        add("simple_fix_bonus", 0.3, "base_rule")

    if getattr(finding, "suggested_text", "") == "":
        add("missing_suggestion_penalty", -0.4, "suggestion_quality")
        risk = "high"

    category = getattr(finding, "issue_category", "").lower()
    if category == "grammar":
        add("grammar_signal", 0.2, "category_signal")
    elif category == "style":
        add("style_signal", 0.1, "category_signal")

    semantic_risk, semantic_evidence, context_flags = _read_semantic_metadata(finding, ctx)

    if semantic_risk == "medium":
        add("meaning_loss_medium_penalty", -0.15, "semantic_evidence")
        if risk == "low":
            risk = "medium"
    elif semantic_risk == "high":
        add("meaning_loss_high_penalty", -0.3, "semantic_evidence")
        risk = "high"

    if semantic_evidence.get("shape_preserved") is False or "sentence_collapse" in context_flags:
        add("semantic_shape_mismatch_penalty", -0.1, "semantic_evidence")
        if risk == "low":
            risk = "medium"

    if semantic_evidence.get("action_preserved") is False or "action_loss" in context_flags:
        add("semantic_action_loss_penalty", -0.1, "semantic_evidence")
        if risk == "low":
            risk = "medium"

    if semantic_evidence.get("entity_alignment_ok") is False or "role_entity_misalignment" in context_flags:
        add("semantic_entity_mismatch_penalty", -0.1, "semantic_evidence")
        risk = "high"

    placeholder_integrity = _read_scalar_evidence(
        finding,
        ctx,
        "placeholder_integrity",
        "placeholder_integrity_by_key",
    )
    if placeholder_integrity == "mismatch":
        add("placeholder_mismatch_penalty", -0.1, "placeholder_integrity")
        if risk == "low":
            risk = "medium"
    elif placeholder_integrity == "missing":
        add("placeholder_missing_penalty", -0.2, "placeholder_integrity")
        risk = "high"

    glossary_alignment = _read_scalar_evidence(
        finding,
        ctx,
        "glossary_alignment",
        "glossary_alignment_by_key",
    )
    if glossary_alignment == "approved":
        add("glossary_alignment_bonus", 0.05, "glossary_signal")
    elif glossary_alignment == "drift":
        add("glossary_drift_penalty", -0.1, "glossary_signal")
        if risk == "low":
            risk = "medium"
    elif glossary_alignment == "violation":
        add("glossary_violation_penalty", -0.15, "glossary_signal")
        if risk != "high":
            risk = "medium"

    structural_consistency = _read_scalar_evidence(
        finding,
        ctx,
        "structural_consistency",
        "structural_consistency_by_key",
    )
    if structural_consistency == "ok":
        add("structural_consistency_bonus", 0.05, "structural_consistency")
    elif structural_consistency == "shape_mismatch":
        add("structural_shape_mismatch_penalty", -0.1, "structural_consistency")
        if risk == "low":
            risk = "medium"
    elif structural_consistency == "nested_collision":
        add("structural_collision_penalty", -0.15, "structural_consistency")
        if risk != "high":
            risk = "medium"

    issue_family = _infer_issue_family(
        finding,
        ctx,
        semantic_risk,
        placeholder_integrity,
        glossary_alignment,
        structural_consistency,
    )

    pre_feedback_confidence = 0.5 + sum(float(contribution["delta"]) for contribution in contributions)
    pre_feedback_route = _route_from_confidence(
        max(0.0, min(1.0, pre_feedback_confidence)),
        finding.is_simple_fix,
    )
    feedback_metrics = _read_feedback_metrics(ctx)
    acceptance_rate = feedback_metrics["acceptance_rate_by_route"].get(pre_feedback_route)
    rejection_rate = feedback_metrics["rejection_rate_by_route"].get(pre_feedback_route)
    avg_confidence = feedback_metrics["avg_confidence_by_route"].get(pre_feedback_route)
    family_acceptance_rate = feedback_metrics["acceptance_rate_by_issue_family"].get(issue_family)
    family_rejection_rate = feedback_metrics["rejection_rate_by_issue_family"].get(issue_family)
    family_avg_confidence = feedback_metrics["avg_confidence_by_issue_family"].get(issue_family)

    if pre_feedback_route == RouteAction.AUTO_FIX.value:
        if acceptance_rate is not None and acceptance_rate >= 0.9:
            add("feedback_autofix_acceptance_bonus", 0.04, "feedback_weighting")
        if rejection_rate is not None and rejection_rate >= 0.2:
            add("feedback_autofix_rejection_penalty", -0.06, "feedback_weighting")
            if risk == "low":
                risk = "medium"
    elif pre_feedback_route == RouteAction.AI_REVIEW.value:
        if acceptance_rate is not None and acceptance_rate >= 0.8:
            add("feedback_ai_review_acceptance_bonus", 0.03, "feedback_weighting")
    elif pre_feedback_route == RouteAction.MANUAL_REVIEW.value:
        if (
            (acceptance_rate is not None and acceptance_rate <= 0.35)
            or (avg_confidence is not None and avg_confidence <= 0.35)
        ):
            add("feedback_manual_review_caution_penalty", -0.02, "feedback_weighting")

    if issue_family == "meaning_loss":
        if (
            (family_rejection_rate is not None and family_rejection_rate >= 0.4)
            or (family_acceptance_rate is not None and family_acceptance_rate <= 0.4)
        ):
            add("feedback_meaning_loss_caution_penalty", -0.05, "feedback_weighting")
            if risk == "low":
                risk = "medium"
    elif issue_family == "grammar":
        if family_acceptance_rate is not None and family_acceptance_rate >= 0.85:
            add("feedback_grammar_acceptance_bonus", 0.03, "feedback_weighting")
    elif issue_family == "style":
        if (
            (family_rejection_rate is not None and family_rejection_rate >= 0.2)
            or (family_avg_confidence is not None and family_avg_confidence <= 0.45)
        ):
            add("feedback_style_caution_penalty", -0.03, "feedback_weighting")
            if risk == "low":
                risk = "medium"
    elif issue_family == "placeholder":
        if family_rejection_rate is not None and family_rejection_rate >= 0.25:
            add("feedback_placeholder_rejection_penalty", -0.05, "feedback_weighting")
            if risk == "low":
                risk = "medium"
    elif issue_family == "glossary":
        if family_acceptance_rate is not None and family_acceptance_rate >= 0.85:
            add("feedback_glossary_acceptance_bonus", 0.03, "feedback_weighting")
    elif issue_family == "structural":
        if (
            (family_rejection_rate is not None and family_rejection_rate >= 0.25)
            or (family_avg_confidence is not None and family_avg_confidence <= 0.45)
        ):
            add("feedback_structural_caution_penalty", -0.04, "feedback_weighting")
            if risk == "low":
                risk = "medium"

    pre_interaction_confidence = 0.5 + sum(float(contribution["delta"]) for contribution in contributions)
    interaction_adjustment_total = 0.0

    def add_interaction(code: str, delta: float, source: str) -> None:
        nonlocal interaction_adjustment_total, risk
        if abs(interaction_adjustment_total + delta) > 0.1:
            return
        add(code, delta, source)
        interaction_adjustment_total = round(interaction_adjustment_total + delta, 6)
        if delta < 0 and risk == "low":
            risk = "medium"

    has_placeholder_issue = placeholder_integrity in {"mismatch", "missing"}
    has_structural_issue = structural_consistency in {"shape_mismatch", "nested_collision"}
    has_glossary_violation = glossary_alignment == "violation"

    if issue_family == "meaning_loss" and has_placeholder_issue:
        add_interaction(
            "cross_evidence_meaning_loss_placeholder_penalty",
            -0.03,
            "cross_evidence",
        )

    if has_structural_issue and pre_interaction_confidence < 0.6:
        add_interaction(
            "cross_evidence_structural_low_confidence_penalty",
            -0.02,
            "cross_evidence",
        )

    if issue_family == "meaning_loss" and has_glossary_violation:
        add_interaction(
            "cross_evidence_glossary_meaning_penalty",
            -0.02,
            "cross_evidence",
        )

    domain = _read_domain(ctx)
    if domain in {"legal", "finance", "security"}:
        add_interaction("domain_low_tolerance_penalty", -0.02, "domain_weighting")
    elif domain in {"marketing", "ux", "content"}:
        add_interaction("domain_high_tolerance_bonus", 0.01, "domain_weighting")

    profile = _read_context_profile_metadata(ctx)
    profile_adjustment_total = 0.0

    def add_profile(code: str, delta: float) -> None:
        nonlocal profile_adjustment_total, risk
        if abs(profile_adjustment_total + delta) > 0.08:
            return
        add(code, delta, "context_profile_weighting")
        profile_adjustment_total = round(profile_adjustment_total + delta, 6)
        if delta < 0 and risk == "low":
            risk = "medium"

    post_domain_confidence = 0.5 + sum(float(contribution["delta"]) for contribution in contributions)
    risk_tolerance = str(profile.get("risk_tolerance", "")).strip().lower()
    if risk_tolerance == "low" and (risk in {"medium", "high"} or 0.35 < post_domain_confidence < 0.85):
        add_profile("profile_low_risk_tolerance_penalty", -0.03)

    style_strictness = profile.get("style_strictness")
    try:
        style_strictness_value = max(0.0, min(float(style_strictness), 1.0))
    except (TypeError, ValueError):
        style_strictness_value = 0.0
    if issue_family == "style" and style_strictness_value > 0.0:
        add_profile("profile_style_strictness_penalty", -min(0.05 * style_strictness_value, 0.05))

    if bool(profile.get("glossary_enforced")) and (
        glossary_alignment in {"drift", "violation"} or issue_family == "glossary"
    ):
        add_profile("profile_glossary_enforced_caution", -0.03)

    if bool(profile.get("prefer_manual_review")) and post_domain_confidence > 0.3 and risk in {"medium", "high"}:
        add_profile("profile_manual_preference_caution", -0.02)

    return contributions, risk, issue_family


def _summarize_contributions(contributions: list[dict[str, object]]) -> list[dict[str, object]]:
    """Build a deterministic per-source summary of confidence contributions."""
    summary_by_source: dict[str, dict[str, object]] = {}
    for contribution in contributions:
        source = str(contribution["source"])
        bucket = summary_by_source.setdefault(
            source,
            {"source": source, "total_delta": 0.0, "codes": [], "kinds": []},
        )
        bucket["total_delta"] = round(float(bucket["total_delta"]) + float(contribution["delta"]), 6)
        bucket["codes"].append(str(contribution["code"]))
        kind = str(contribution["kind"])
        if kind not in bucket["kinds"]:
            bucket["kinds"].append(kind)

    return [summary_by_source[source] for source in sorted(summary_by_source)]


def _read_semantic_metadata(finding: LTFinding, ctx: DecisionContext) -> tuple[str, dict[str, Any], list[str]]:
    """Read optional semantic evidence from finding metadata or context metadata."""
    semantic_risk = str(
        getattr(finding, "semantic_risk", "")
        or ctx.metadata.get("semantic_risk_by_key", {}).get(getattr(finding, "key", ""), "")
        or ""
    ).strip().lower()
    semantic_evidence = (
        getattr(finding, "semantic_evidence", None)
        or getattr(finding, "_semantic_evidence", None)
        or ctx.metadata.get("semantic_evidence_by_key", {}).get(getattr(finding, "key", ""), {})
        or {}
    )
    if not isinstance(semantic_evidence, dict):
        semantic_evidence = {}
    context_flags = (
        getattr(finding, "context_flags", None)
        or getattr(finding, "_context_flags", None)
        or ctx.metadata.get("context_flags_by_key", {}).get(getattr(finding, "key", ""), [])
        or []
    )
    if not isinstance(context_flags, list):
        context_flags = []
    return semantic_risk, semantic_evidence, [str(flag) for flag in context_flags]

def score_finding(finding: LTFinding, ctx: DecisionContext) -> dict:
    """Evaluate finding context to determine deterministic risk and confidence levels."""
    if ctx is None:
        ctx = DecisionContext(findings=[finding], source="unknown")
    base_confidence = 0.5
    score_factors, risk, issue_family = _build_evidence_contributions(finding, ctx)
    explanation_codes = [str(factor["code"]) for factor in score_factors]
    confidence = base_confidence + sum(float(factor["delta"]) for factor in score_factors)
    evidence_sources = [str(factor["source"]) for factor in score_factors]
    contribution_summary = _summarize_contributions(score_factors)
    confidence_evidence = {
        "feedback_sources": _build_confidence_feedback_sources(score_factors),
    }
    context_profile_signals = _build_context_profile_signals(score_factors)

    return {
        "base_confidence": base_confidence,
        "confidence": max(0.0, min(1.0, confidence)),
        "risk": risk,
        "score_factors": score_factors,
        "explanation_codes": explanation_codes,
        "evidence_sources": evidence_sources,
        "contribution_summary": contribution_summary,
        "issue_family": issue_family,
        "confidence_evidence": confidence_evidence,
        "context_profile_signals": context_profile_signals,
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
        score_metadata = dict(ctx.metadata)
        if context_profile is not None:
            if "domain" not in score_metadata:
                score_metadata["domain"] = getattr(context_profile, "domain", "")
            if "context_profile" not in score_metadata:
                score_metadata["context_profile"] = {
                    "domain": getattr(context_profile, "domain", ""),
                    "risk_tolerance": getattr(context_profile, "risk_tolerance", ""),
                    "style_strictness": getattr(context_profile, "style_strictness", None),
                    "prefer_manual_review": getattr(context_profile, "prefer_manual_review", False),
                    "glossary_enforced": getattr(context_profile, "glossary_enforced", False),
                }
        score = score_finding(finding, DecisionContext(findings=[finding], source=ctx.source, metadata=score_metadata))
        finding.confidence_score = score["confidence"]
        finding.risk_level = score["risk"]
        base_route = RouteAction.AI_REVIEW
        explanation_codes = list(score["explanation_codes"])

        # Step 2: Base Route Assignment (Phase 7 Thresholds)
        if score["confidence"] >= 0.8 and finding.is_simple_fix:
            assigned_route = RouteAction.AUTO_FIX
        elif score["confidence"] <= 0.3:
            assigned_route = RouteAction.MANUAL_REVIEW
        else:
            assigned_route = RouteAction.AI_REVIEW
        base_route = assigned_route

        # Step 3: Phase 9 Calibration (Post-Processing Override)
        route_after_calibration = assigned_route
        if profiles is not None:
            assigned_route = cal_engine.calibrate_route(
                assigned_route,
                finding.confidence_score,
                finding.is_simple_fix,
                profiles
            )
            route_after_calibration = assigned_route
            if route_after_calibration != base_route:
                explanation_codes.append("calibration_downgrade")
                context_metrics.record_calibration_route_change()

        # Step 4: Phase 12 Context Adjustment (after scoring + calibration, before queue commit)
        context_adj = None
        route_after_context = assigned_route
        if context_profile is not None:
            assigned_route, context_adj = apply_context_rules(
                finding, assigned_route, context_profile
            )
            context_metrics.record_context_adjustment(
                context_adj.rules_triggered,
                route_changed=(context_adj.route_before != context_adj.route_after),
            )
            route_after_context = assigned_route
            for code in context_adj.rules_triggered:
                if code in DECISION_EXPLANATION_CODES and code not in explanation_codes:
                    explanation_codes.append(code)

        # Attach context decision payload to finding for downstream observability
        finding._context_adjustment = context_adj
        finding._decision_explanation = {
            "score_factors": list(score["score_factors"]),
            "base_confidence": score["base_confidence"],
            "final_confidence": finding.confidence_score,
            "risk": finding.risk_level,
            "issue_family": score["issue_family"],
            "evidence_sources": list(score["evidence_sources"]),
            "contribution_summary": list(score["contribution_summary"]),
            "confidence_evidence": dict(score["confidence_evidence"]),
            "context_profile_signals": list(score["context_profile_signals"]),
            "route_before_calibration": base_route.value,
            "route_after_calibration": route_after_calibration.value,
            "route_after_context": route_after_context.value,
            "explanation_codes": explanation_codes,
        }
        context_metrics.record_decision_explanation()

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
            "decision_explanation": getattr(finding, "_decision_explanation", {}),
        }
        metrics.record(route)
        if hasattr(metrics, "record_adaptive"):
            metrics.record_adaptive(finding.confidence_score, finding.risk_level)

    import json
    logger.info("Routing Metrics [arabic_pipeline]: %s", json.dumps(metrics.to_dict()))
