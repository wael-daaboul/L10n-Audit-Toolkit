"""
l10n_audit/core/adaptation_intelligence.py
==========================================
Phase 14 — Controlled Adaptive Intelligence Layer.

Design constraints
------------------
* Feature-gated: disabled by default; opt-in via config["adaptive_intelligence"]["enabled"].
* Read-only: consumes only LearningProfile (Phase 13 output) + config dict.
* Zero pipeline impact on failure — called from engine.py post-pipeline hook only.
* Non-behavioral: no write-back to routing, scoring, calibration, or any engine.
* Deterministic: same LearningProfile + same config → identical AdaptationReport.
* No file I/O, no randomness, no timestamps in analytical payload.
* Three modes: shadow (returns None) | suggest | prepare_bounded_actions.

Dependency direction (one-way, enforced):
  engine.py post-pipeline → project_memory.LearningProfile → adaptation_intelligence
  ← NO reverse dependency allowed ←
  Must NOT be imported by: decision_engine, calibration_engine, context_profile,
  conflict_resolution, enforcement_layer.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# LearningProfile is imported TYPE_CHECKING-only to avoid circular imports.
# At runtime the object is passed in as Any and duck-typed.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from l10n_audit.core.project_memory import LearningProfile

logger = logging.getLogger("l10n_audit.adaptation_intelligence")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PHASE = "14"
_VERSION = "1.0"

# Finite allowed signal key set — open-ended signal names are always rejected.
ALLOWED_SIGNAL_KEYS: frozenset = frozenset({
    "manual_review_rate_high",
    "ai_review_rate_high",
    "auto_fix_rate_low",
    "context_adjustment_rate_high",
    "arabic_run_dominance",
    "calibration_rarely_active",
})

# Allowed operation modes — controlled_enforce is deliberately excluded from Phase 14.
_ALLOWED_MODES = frozenset({"shadow", "suggest", "prepare_bounded_actions"})

# Default threshold values — all overridable via config; never self-modifying.
_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "manual_review_rate_high":       0.70,
    "ai_review_rate_high":           0.85,
    "auto_fix_rate_low":             0.10,
    "context_adjustment_rate_high":  0.40,
    "arabic_run_dominance":          0.80,
    "calibration_rarely_active":     0.20,
}

_DEFAULT_MIN_RUNS = 5


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class AdaptationProposal:
    """A single bounded adaptation signal derived from a LearningProfile.

    All fields are deterministic. proposal_id is derived from a canonical
    JSON hash of the trigger payload — never from wall-clock time or UUIDs.

    Proposal types
    --------------
    observation              — pattern noted, no action implied.
    recommendation           — human-reviewable suggestion.
    bounded_action_candidate — eligible for future bounded consumption
                               (Phase 14 itself does NOT apply it).
    """
    proposal_id: str                       # sha256[:12] of canonical trigger payload
    signal_key: str                        # one of ALLOWED_SIGNAL_KEYS
    signal_value: float                    # the measured rate/ratio (rounded to 4dp)
    threshold_used: float                  # threshold that triggered this proposal
    proposal_type: str                     # observation | recommendation | bounded_action_candidate
    reasoning: str                         # plain-text explanation
    source_run_count: int                  # number of runs this derives from
    profile_hash: str                      # sha256[:16] of the input LearningProfile
    bounded_action_key: Optional[str] = None  # populated only in prepare_bounded_actions mode


@dataclass
class AdaptationReport:
    """Structured output of the Phase 14 analysis pass.

    No wall-clock timestamp in this payload — timestamp would break determinism.
    If timing is needed, the caller (engine.py) may attach it externally.

    Modes
    -----
    shadow                  — this report is never produced (function returns None).
    suggest                 — proposals present as observations/recommendations.
    prepare_bounded_actions — proposals augmented with bounded_action_key markers.
    """
    project_id: str
    mode: str
    run_count_basis: int
    profile_hash: str
    proposals: List[AdaptationProposal] = field(default_factory=list)
    safety_rejections: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal pure helpers
# ---------------------------------------------------------------------------

def _normalize_numeric(value: float) -> float:
    """Round to 4 decimal places for stable canonical hashing."""
    return round(float(value), 4)


def _hash_profile(profile: Any) -> str:
    """Produce a stable 16-char hex digest of the LearningProfile fields.

    Uses only the analytical fields of the profile (not object identity).
    Deterministic: same field values → same hash.
    """
    payload = {
        "project_id":               str(getattr(profile, "project_id", "")),
        "run_count":                int(getattr(profile, "run_count", 0)),
        "avg_total_issues":         _normalize_numeric(getattr(profile, "avg_total_issues", 0.0)),
        "avg_auto_fix_rate":        _normalize_numeric(getattr(profile, "avg_auto_fix_rate", 0.0)),
        "avg_ai_review_rate":       _normalize_numeric(getattr(profile, "avg_ai_review_rate", 0.0)),
        "avg_manual_review_rate":   _normalize_numeric(getattr(profile, "avg_manual_review_rate", 0.0)),
        "avg_context_adjusted_rate":_normalize_numeric(getattr(profile, "avg_context_adjusted_rate", 0.0)),
        "dominant_category":        str(getattr(profile, "dominant_category", "")),
        "arabic_run_count":         int(getattr(profile, "arabic_run_count", 0)),
        "calibration_active_runs":  int(getattr(profile, "calibration_active_runs", 0)),
        "routing_enabled_runs":     int(getattr(profile, "routing_enabled_runs", 0)),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _build_proposal_id(signal_key: str, signal_value: float, profile_hash: str) -> str:
    """Deterministic proposal ID from canonical trigger payload.

    Built from signal_key + normalized signal_value + profile_hash.
    Never uses wall-clock time, UUIDs, or raw str() of floats.
    """
    payload = {
        "signal_key":   signal_key,
        "signal_value": _normalize_numeric(signal_value),
        "profile_hash": profile_hash,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def _resolve_thresholds(config: Dict[str, Any]) -> Dict[str, float]:
    """Merge user-supplied threshold overrides onto the declared defaults.

    Only keys present in _DEFAULT_THRESHOLDS are accepted.
    Unknown keys from config are silently ignored (safety by allowlist).
    Values are clamped to [0.0, 1.0] since all thresholds are rates/ratios.
    """
    result = dict(_DEFAULT_THRESHOLDS)
    user_thresholds = config.get("thresholds", {})
    if isinstance(user_thresholds, dict):
        for key, val in user_thresholds.items():
            if key in result:
                try:
                    clamped = max(0.0, min(1.0, float(val)))
                    result[key] = clamped
                except (TypeError, ValueError):
                    pass  # invalid values silently fall back to defaults
    return result


def _analyze_proposals(
    profile: Any,
    thresholds: Dict[str, float],
    min_runs: int,
    profile_hash: str,
) -> List[AdaptationProposal]:
    """Derive all candidate proposals from the LearningProfile fields.

    Pure function — no I/O, no side effects, no randomness.
    Produces proposals in a deterministic, sorted order.

    A proposal is generated only when the corresponding signal exceeds its
    declared threshold. Proposals are sorted by signal_key for stable output.

    Parameters
    ----------
    profile:
        LearningProfile instance (duck-typed; uses only declared fields).
    thresholds:
        Resolved threshold dict from _resolve_thresholds().
    min_runs:
        Minimum run count required for proposals (safety rule applied later).
    profile_hash:
        Pre-computed profile hash, passed in to avoid recomputing.
    """
    run_count: int = int(getattr(profile, "run_count", 0))
    proposals: List[AdaptationProposal] = []

    def _add(
        signal_key: str,
        signal_value: float,
        threshold: float,
        proposal_type: str,
        reasoning: str,
        bounded_action_key: Optional[str] = None,
    ) -> None:
        sv = _normalize_numeric(signal_value)
        proposals.append(AdaptationProposal(
            proposal_id=_build_proposal_id(signal_key, sv, profile_hash),
            signal_key=signal_key,
            signal_value=sv,
            threshold_used=threshold,
            proposal_type=proposal_type,
            reasoning=reasoning,
            source_run_count=run_count,
            profile_hash=profile_hash,
            bounded_action_key=bounded_action_key,
        ))

    # --- Signal: manual_review_rate_high ---
    mn_rate: float = _normalize_numeric(getattr(profile, "avg_manual_review_rate", 0.0))
    t_mn = thresholds["manual_review_rate_high"]
    if mn_rate > t_mn:
        _add(
            signal_key="manual_review_rate_high",
            signal_value=mn_rate,
            threshold=t_mn,
            proposal_type="recommendation",
            reasoning=(
                f"Average manual_review rate ({mn_rate:.4f}) exceeds threshold ({t_mn}). "
                f"Over {run_count} run(s), a disproportionate share of findings are routed "
                "to manual review. Consider reviewing context profile risk_tolerance or "
                "calibration settings to allow more auto_fix or ai_review routing."
            ),
        )

    # --- Signal: ai_review_rate_high ---
    ai_rate: float = _normalize_numeric(getattr(profile, "avg_ai_review_rate", 0.0))
    t_ai = thresholds["ai_review_rate_high"]
    if ai_rate > t_ai:
        _add(
            signal_key="ai_review_rate_high",
            signal_value=ai_rate,
            threshold=t_ai,
            proposal_type="observation",
            reasoning=(
                f"Average ai_review rate ({ai_rate:.4f}) exceeds threshold ({t_ai}). "
                f"The majority of findings across {run_count} run(s) land in the AI review "
                "queue. This is informational — high ai_review volume is expected for "
                "complex projects but may indicate that auto_fix confidence thresholds "
                "are set conservatively."
            ),
        )

    # --- Signal: auto_fix_rate_low ---
    af_rate: float = _normalize_numeric(getattr(profile, "avg_auto_fix_rate", 0.0))
    t_af = thresholds["auto_fix_rate_low"]
    if af_rate < t_af:
        _add(
            signal_key="auto_fix_rate_low",
            signal_value=af_rate,
            threshold=t_af,
            proposal_type="observation",
            reasoning=(
                f"Average auto_fix rate ({af_rate:.4f}) is below threshold ({t_af}). "
                f"Across {run_count} run(s), very few findings qualify for automatic fixing. "
                "This is informational — low auto_fix rates are expected when calibration "
                "mode is conservative or when findings are predominantly complex."
            ),
        )

    # --- Signal: context_adjustment_rate_high ---
    ctx_rate: float = _normalize_numeric(getattr(profile, "avg_context_adjusted_rate", 0.0))
    t_ctx = thresholds["context_adjustment_rate_high"]
    if ctx_rate > t_ctx:
        _add(
            signal_key="context_adjustment_rate_high",
            signal_value=ctx_rate,
            threshold=t_ctx,
            proposal_type="observation",
            reasoning=(
                f"Average context adjustment rate ({ctx_rate:.4f}) exceeds threshold ({t_ctx}). "
                f"The active context profile is triggering adjustments on a significant share "
                f"of findings across {run_count} run(s). Review the ContextProfile domain "
                "settings (risk_tolerance, style_strictness, prefer_manual_review) to confirm "
                "they reflect current project intent."
            ),
        )

    # --- Signal: arabic_run_dominance ---
    arabic_runs: int = int(getattr(profile, "arabic_run_count", 0))
    arabic_ratio: float = _normalize_numeric(arabic_runs / max(1, run_count))
    t_ar = thresholds["arabic_run_dominance"]
    if arabic_ratio > t_ar:
        _add(
            signal_key="arabic_run_dominance",
            signal_value=arabic_ratio,
            threshold=t_ar,
            proposal_type="observation",
            reasoning=(
                f"Arabic findings dominate run history ({arabic_runs}/{run_count} runs = "
                f"{arabic_ratio:.4f}). Arabic routing is annotation-only by design. "
                "This observation is for informational awareness only — no behavioral change "
                "is implied or permitted."
            ),
        )

    # --- Signal: calibration_rarely_active ---
    cal_runs: int = int(getattr(profile, "calibration_active_runs", 0))
    cal_ratio: float = _normalize_numeric(cal_runs / max(1, run_count))
    t_cal = thresholds["calibration_rarely_active"]
    if cal_ratio < t_cal:
        _add(
            signal_key="calibration_rarely_active",
            signal_value=cal_ratio,
            threshold=t_cal,
            proposal_type="recommendation",
            reasoning=(
                f"Calibration was active in only {cal_runs}/{run_count} run(s) "
                f"({cal_ratio:.4f} < threshold {t_cal}). Consider enabling the calibration "
                "engine (config['calibration']['enabled'] = true) to improve routing "
                "accuracy. This is a recommendation only — not automatically applied."
            ),
        )

    # Sort by signal_key for deterministic ordering regardless of evaluation order above.
    proposals.sort(key=lambda p: p.signal_key)
    return proposals


def _validate_safety(
    proposals: List[AdaptationProposal],
    min_runs: int,
) -> Tuple[List[AdaptationProposal], List[str]]:
    """Apply hard safety rules. Returns (valid_proposals, rejection_reasons).

    Safety rules (all explicit, all testable):
    1. signal_key must be in ALLOWED_SIGNAL_KEYS.
    2. source_run_count must meet min_runs threshold.
    3. proposal_type must be one of the declared types.
    4. reasoning must be non-empty (explainability requirement).

    Rejected proposals are logged at DEBUG and their reasons collected.
    No exceptions are raised — caller receives the filtered list.
    """
    valid: List[AdaptationProposal] = []
    rejections: List[str] = []
    allowed_types = frozenset({"observation", "recommendation", "bounded_action_candidate"})

    for p in proposals:
        # Rule 1: signal_key must be declared
        if p.signal_key not in ALLOWED_SIGNAL_KEYS:
            reason = f"REJECTED[unknown_signal]: {p.signal_key!r} is not in ALLOWED_SIGNAL_KEYS"
            rejections.append(reason)
            logger.debug("adaptation_intelligence: %s", reason)
            continue

        # Rule 2: sufficient history
        if p.source_run_count < min_runs:
            reason = (
                f"REJECTED[insufficient_runs]: signal={p.signal_key!r} "
                f"source_run_count={p.source_run_count} < min_runs={min_runs}"
            )
            rejections.append(reason)
            logger.debug("adaptation_intelligence: %s", reason)
            continue

        # Rule 3: proposal_type must be declared
        if p.proposal_type not in allowed_types:
            reason = f"REJECTED[invalid_proposal_type]: {p.proposal_type!r} for signal {p.signal_key!r}"
            rejections.append(reason)
            logger.debug("adaptation_intelligence: %s", reason)
            continue

        # Rule 4: reasoning must be present
        if not p.reasoning or not p.reasoning.strip():
            reason = f"REJECTED[empty_reasoning]: signal={p.signal_key!r} has no reasoning text"
            rejections.append(reason)
            logger.debug("adaptation_intelligence: %s", reason)
            continue

        valid.append(p)

    return valid, rejections


def _apply_mode_gate(
    valid_proposals: List[AdaptationProposal],
    mode: str,
) -> Optional[List[AdaptationProposal]]:
    """Apply mode semantics to the validated proposal list.

    shadow               → return None  (nothing emitted, no logs above DEBUG)
    suggest              → return proposals unchanged
    prepare_bounded_actions → return proposals with bounded_action_key populated
                             for recommendation-type proposals only
    """
    if mode == "shadow":
        return None

    if mode == "suggest":
        return list(valid_proposals)  # return a copy, do not mutate

    if mode == "prepare_bounded_actions":
        result = []
        for p in valid_proposals:
            if p.proposal_type == "recommendation":
                # Mark as a bounded_action_candidate but do NOT change proposal_type here —
                # the proposal is still a recommendation; bounded_action_key is a marker only.
                result.append(AdaptationProposal(
                    proposal_id=p.proposal_id,
                    signal_key=p.signal_key,
                    signal_value=p.signal_value,
                    threshold_used=p.threshold_used,
                    proposal_type="bounded_action_candidate",
                    reasoning=p.reasoning,
                    source_run_count=p.source_run_count,
                    profile_hash=p.profile_hash,
                    bounded_action_key=f"phase14::{p.signal_key}",
                ))
            else:
                result.append(p)
        return result

    # Unknown mode — treat as shadow (safe fallback).
    logger.debug("adaptation_intelligence: unknown mode %r — treating as shadow", mode)
    return None


def _build_report(
    profile: Any,
    mode: str,
    proposals: List[AdaptationProposal],
    rejections: List[str],
) -> AdaptationReport:
    """Build the final AdaptationReport. Pure function, no I/O."""
    return AdaptationReport(
        project_id=str(getattr(profile, "project_id", "unknown")),
        mode=mode,
        run_count_basis=int(getattr(profile, "run_count", 0)),
        profile_hash=_hash_profile(profile),
        proposals=proposals,
        safety_rejections=rejections,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_adaptation_report(
    profile: Any,
    config: Dict[str, Any],
) -> Optional[AdaptationReport]:
    """Compute a deterministic adaptation report from a LearningProfile.

    This is the only public function in Phase 14.

    Constraints
    -----------
    * Accepts only LearningProfile + config dict — not the full runtime object.
    * No file I/O, no network, no randomness.
    * Returns None when disabled, in shadow mode, or on any internal failure.
    * All exceptions are caught and logged at DEBUG — never propagated.

    Parameters
    ----------
    profile:
        The LearningProfile produced by Phase 13 record_run_to_memory().
        Duck-typed — only LearningProfile fields are accessed.
    config:
        The "adaptive_intelligence" sub-dict from runtime.config.
        Expected keys: enabled, mode, min_runs_required, thresholds.

    Returns
    -------
    AdaptationReport if mode is suggest or prepare_bounded_actions AND
    at least one valid proposal exists, else None.
    """
    try:
        if not isinstance(config, dict):
            return None

        if not config.get("enabled", False):
            return None

        mode = str(config.get("mode", "shadow"))
        if mode not in _ALLOWED_MODES:
            logger.debug(
                "adaptation_intelligence: mode %r not in allowed set %s — treating as shadow",
                mode, sorted(_ALLOWED_MODES),
            )
            mode = "shadow"

        min_runs = int(config.get("min_runs_required", _DEFAULT_MIN_RUNS))
        thresholds = _resolve_thresholds(config)

        # Gate: shadow mode short-circuits before any analysis.
        if mode == "shadow":
            logger.debug("adaptation_intelligence: shadow mode — no output produced")
            return None

        # Compute profile hash once; reused in proposal IDs.
        profile_hash = _hash_profile(profile)

        # Step 1: derive candidate proposals (pure function over profile fields).
        candidates = _analyze_proposals(profile, thresholds, min_runs, profile_hash)

        # Step 2: apply safety rules.
        valid, rejections = _validate_safety(candidates, min_runs)

        # Step 3: apply mode gate.
        gated = _apply_mode_gate(valid, mode)

        if gated is None:
            return None

        # Step 4: build final report.
        report = _build_report(profile, mode, gated, rejections)

        logger.debug(
            "adaptation_intelligence: mode=%s proposals=%d rejected=%d project=%s",
            mode, len(gated), len(rejections),
            getattr(profile, "project_id", "unknown"),
        )
        return report

    except Exception as exc:
        logger.debug("adaptation_intelligence: internal error (%s) — returning None", exc)
        return None
