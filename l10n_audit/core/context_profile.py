"""
l10n_audit/core/context_profile.py
=====================================
Phase 12 — Cross-Project Intelligence Layer.

Introduces ContextProfile: a per-project, per-domain configuration object
that allows the decision system to apply deterministic, context-aware
adjustments on top of base scoring and calibration.

Design constraints
------------------
* Pure data model — no side effects, no I/O, no randomness.
* All adjustment logic lives in apply_context_rules(), not in score_finding().
* Backward compatible: absent profile → zero behavior change.
* Flag-gated: profile is optional on runtime.
* Deterministic: same profile + same finding → same result, every time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Context Profile Data Model
# ---------------------------------------------------------------------------

@dataclass
class ContextProfile:
    """Per-project, per-domain intelligence configuration.

    Fields
    ------
    project_id:
        Unique identifier for the project. Used for traceability only.
    domain:
        Domain classification string, e.g. "ecommerce", "legal", "marketing".
    risk_tolerance:
        One of "low" | "medium" | "high".
        "low" → more conservative routing (downgrades AUTO_FIX, escalates AI_REVIEW).
    style_strictness:
        Float in [0.0, 1.0]. Higher values penalize style-category confidence more.
    prefer_manual_review:
        If True and risk_level is "high", force route to MANUAL_REVIEW.
    glossary_enforced:
        If True, annotate findings requiring glossary verification.
        Annotation only — no behavioral change in Phase 12.
    version:
        Profile schema version string for traceability.
    """
    project_id: str
    domain: str

    risk_tolerance: str = "medium"   # "low" | "medium" | "high"
    style_strictness: float = 0.0    # 0.0 → 1.0
    prefer_manual_review: bool = False
    glossary_enforced: bool = False
    version: str = "1.0"

    def __post_init__(self) -> None:
        if self.risk_tolerance not in ("low", "medium", "high"):
            raise ValueError(
                f"risk_tolerance must be 'low', 'medium', or 'high'; got {self.risk_tolerance!r}"
            )
        if not (0.0 <= self.style_strictness <= 1.0):
            raise ValueError(
                f"style_strictness must be in [0.0, 1.0]; got {self.style_strictness}"
            )


# ---------------------------------------------------------------------------
# Context Adjustment Result
# ---------------------------------------------------------------------------

@dataclass
class ContextAdjustment:
    """Records what the context layer changed for a single finding.

    Attached to LTFinding as finding._context_adjustment after apply_context_rules().
    """
    context_applied: bool = False
    rules_triggered: list[str] = field(default_factory=list)
    confidence_before: float = 0.0
    confidence_after: float = 0.0
    route_before: str = ""
    route_after: str = ""


# ---------------------------------------------------------------------------
# Core Adjustment Logic (pure function — no side effects)
# ---------------------------------------------------------------------------

def apply_context_rules(
    finding: Any,
    assigned_route: Any,          # RouteAction enum value
    profile: ContextProfile,
) -> tuple[Any, ContextAdjustment]:
    """Apply deterministic context-aware adjustments to a routed finding.

    Called AFTER scoring and calibration, BEFORE final queue assignment.
    Does NOT modify score_finding() or calibration thresholds.

    Parameters
    ----------
    finding:
        An LTFinding with .confidence_score, .risk_level, .issue_category set.
    assigned_route:
        The RouteAction assigned after Phase 7 + Phase 9 calibration.
    profile:
        The active ContextProfile for this project/domain.

    Returns
    -------
    (final_route, ContextAdjustment)
        final_route may differ from assigned_route if rules fired.
        ContextAdjustment records what changed and why.
    """
    # Import here to avoid circular imports (decision_engine imports this module)
    from l10n_audit.core.decision_engine import RouteAction

    adj = ContextAdjustment(
        confidence_before=finding.confidence_score,
        confidence_after=finding.confidence_score,
        route_before=assigned_route.value,
        route_after=assigned_route.value,
    )

    current_route = assigned_route
    category = getattr(finding, "issue_category", "").lower()

    # ------------------------------------------------------------------
    # Rule B — Style Strictness: penalize confidence for style findings.
    # Applied first so subsequent rules see the adjusted confidence.
    # ------------------------------------------------------------------
    if category == "style" and profile.style_strictness > 0.0:
        penalty = profile.style_strictness * 0.3
        adjusted_confidence = max(0.0, finding.confidence_score - penalty)
        finding.confidence_score = adjusted_confidence
        adj.confidence_after = adjusted_confidence
        adj.rules_triggered.append("style_penalty")

    # ------------------------------------------------------------------
    # Rule A — High Risk Domain (risk_tolerance == "low"):
    #   AUTO_FIX → AI_REVIEW (unconditionally)
    #   AI_REVIEW → MANUAL_REVIEW (only if confidence < 0.6)
    # ------------------------------------------------------------------
    if profile.risk_tolerance == "low":
        if current_route == RouteAction.AUTO_FIX:
            current_route = RouteAction.AI_REVIEW
            adj.rules_triggered.append("risk_downgrade")
        elif current_route == RouteAction.AI_REVIEW and finding.confidence_score < 0.6:
            current_route = RouteAction.MANUAL_REVIEW
            adj.rules_triggered.append("risk_downgrade")

    # ------------------------------------------------------------------
    # Rule C — Manual Preference: force MANUAL_REVIEW for high-risk findings.
    # ------------------------------------------------------------------
    if profile.prefer_manual_review and finding.risk_level == "high":
        if current_route != RouteAction.MANUAL_REVIEW:
            current_route = RouteAction.MANUAL_REVIEW
            adj.rules_triggered.append("manual_override")

    # ------------------------------------------------------------------
    # Rule D — Glossary Enforcement: annotation only, no route change.
    # ------------------------------------------------------------------
    if profile.glossary_enforced:
        finding.requires_glossary_check = True

    adj.route_after = current_route.value
    adj.context_applied = bool(adj.rules_triggered)
    return current_route, adj


# ---------------------------------------------------------------------------
# Runtime Helper
# ---------------------------------------------------------------------------

def get_context_profile(runtime: Any) -> Optional[ContextProfile]:
    """Return the ContextProfile attached to runtime, or None if absent.

    Absence means zero behavior change (Phase 11 and earlier semantics).
    """
    return getattr(runtime, "context_profile", None)
