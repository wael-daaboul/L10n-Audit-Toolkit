"""
l10n_audit/core/calibration_engine.py
======================================
Phase 9 — Confidence Calibration & Adaptive Thresholding.

Implements a deterministic calibration layer that sits between the Decision
Engine (Phase 7) and the Enforcement Layer (Phase 6).

It reads Phase 8 feedback signals to adjust routing thresholds without
modifying the base scoring heuristics in score_finding().

Design guarantees
-----------------
* No behavior change when disabled (config flag gated).
* Only downgrades routes — never upgrades aggressively in v1.
  auto_fix → ai_review is allowed; ai_review → auto_fix is NOT.
* Deterministic: same feedback state → same calibrated thresholds.
* Per-run only: no calibration state is persisted across runs in v1.
* Three operational modes: shadow | suggest | enforce.

Does NOT modify:
- feedback_engine.py
- enforcement_layer.py
- decision_engine.evaluate_findings() heuristics
- CLI behavior
- Any file outputs
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("l10n_audit.calibration")

# ---------------------------------------------------------------------------
# Route threshold defaults — mirror decision_engine.py evaluate_findings()
# ---------------------------------------------------------------------------

_DEFAULT_AUTO_FIX_THRESHOLD: float = 0.8   # confidence >= 0.8 AND is_simple_fix
_DEFAULT_MANUAL_THRESHOLD:   float = 0.3   # confidence <= 0.3

_AUTOFIX_THRESHOLD_MIN: float = 0.7        # absolute floor (spec constraint)
_AUTOFIX_THRESHOLD_MAX: float = 1.0
_MANUAL_THRESHOLD_MAX:  float = 0.4        # absolute ceiling (spec constraint)
_MANUAL_THRESHOLD_MIN:  float = 0.0

# Expected acceptance rates per route (system design targets)
_TARGET_ACCEPTANCE: Dict[str, float] = {
    "auto_fix":      0.90,
    "ai_review":     0.70,
    "manual_review": 0.50,
}


# ---------------------------------------------------------------------------
# CalibrationProfile
# ---------------------------------------------------------------------------

@dataclass
class CalibrationProfile:
    """Learned calibration state for a single routing queue.

    Fields
    ------
    route:
        Routing queue this profile applies to (e.g. "auto_fix").
    target_acceptance_rate:
        Expected fraction of signals that should be accepted (design target).
    observed_acceptance_rate:
        Actual fraction observed in Phase 8 feedback_metrics.
    confidence_adjustment:
        Positive delta applied to the confidence threshold for this route.
        Clipped to max_adjustment_per_run (default 0.05). Zero when no data.
    min_confidence_threshold:
        Calibrated minimum confidence required to be assigned this route.
    max_confidence_threshold:
        Upper bound (semantically used for MANUAL_REVIEW ceiling).
    """
    route: str
    target_acceptance_rate: float
    observed_acceptance_rate: float
    confidence_adjustment: float
    min_confidence_threshold: float
    max_confidence_threshold: float


# ---------------------------------------------------------------------------
# Module-level override function (called by the decision_engine.py hook)
# ---------------------------------------------------------------------------

def _apply_threshold_override(
    route: Any,             # RouteAction enum value
    confidence: float,
    is_simple_fix: bool,
    profiles: Dict[str, "CalibrationProfile"],
) -> Any:
    """Apply a downgrade-only calibration override to an already-assigned route.

    Permitted in v1:   auto_fix → ai_review
    NOT permitted:     ai_review → auto_fix   (explicit spec constraint)

    Parameters
    ----------
    route:
        The RouteAction already assigned by evaluate_findings.
    confidence:
        The confidence_score from score_finding (clamped [0.0, 1.0]).
    is_simple_fix:
        The is_simple_fix flag from the LTFinding.
    profiles:
        Dict[route_str → CalibrationProfile] from CalibrationEngine.build_profiles().

    Returns
    -------
    A RouteAction — possibly downgraded from auto_fix to ai_review, never upgraded.
    """
    # Deferred import to avoid circular dependency with decision_engine
    from l10n_audit.core.decision_engine import RouteAction

    if route == RouteAction.AUTO_FIX:
        profile = profiles.get("auto_fix")
        if profile is not None:
            if not (confidence >= profile.min_confidence_threshold and is_simple_fix):
                return RouteAction.AI_REVIEW  # downgrade: auto_fix → ai_review

    # No other downgrades in v1
    return route


# ---------------------------------------------------------------------------
# CalibrationEngine
# ---------------------------------------------------------------------------

class CalibrationEngine:
    """Builds calibration profiles from Phase 8 feedback and applies soft overrides.

    This engine is pure and deterministic: given the same feedback_metrics dict,
    it always produces the same profiles and threshold adjustments.

    Typical lifecycle
    -----------------
    engine = CalibrationEngine.from_runtime(runtime)
    if engine is not None and runtime.metadata.get("feedback_metrics"):
        profiles = engine.build_profiles(runtime.metadata["feedback_metrics"])
        engine.store_calibration_metrics(runtime, profiles)
        # profiles passed into evaluate_findings(ctx, calibration_profiles=profiles,
        #                                         calibration_mode=engine.mode)
    """

    def __init__(self, mode: str = "shadow", max_adjustment: float = 0.05) -> None:
        if mode not in ("shadow", "suggest", "enforce"):
            raise ValueError(f"Invalid calibration mode: {mode!r}. Must be shadow|suggest|enforce.")
        self.mode = mode
        self.max_adjustment = max(0.0, min(0.1, max_adjustment))  # clamp to [0, 0.1]

    # ------------------------------------------------------------------
    # Factory & config helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_runtime(cls, runtime: object) -> "Optional[CalibrationEngine]":
        """Return a CalibrationEngine if calibration is enabled in config, else None."""
        try:
            config = getattr(runtime, "config", {})
            if not isinstance(config, dict):
                return None
            cal_config = config.get("calibration", {})
            if not isinstance(cal_config, dict):
                return None
            if not cal_config.get("enabled", False):
                return None
            mode      = str(cal_config.get("mode", "shadow"))
            max_adj   = float(cal_config.get("max_adjustment_per_run", 0.05))
            return cls(mode=mode, max_adjustment=max_adj)
        except Exception:
            return None

    @staticmethod
    def is_calibration_enabled(runtime: object) -> bool:
        """Return True if calibration is enabled in runtime config."""
        try:
            config = getattr(runtime, "config", {})
            if not isinstance(config, dict):
                return False
            return bool(config.get("calibration", {}).get("enabled", False))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Profile building
    # ------------------------------------------------------------------

    def build_profiles(self, feedback_metrics: dict) -> Dict[str, CalibrationProfile]:
        """Build CalibrationProfile objects from Phase 8 feedback_metrics.

        Algorithm (deterministic)
        -------------------------
        For each route with a design target acceptance rate:

          excess_rejection = observed_rejection - (1 - target_acceptance)

          if excess_rejection > 0:  # route is over-confident
              adjustment = min(max_adjustment, excess_rejection)
          else:
              adjustment = 0.0      # never loosen threshold in v1

        AUTO_FIX: raise min_confidence_threshold by adjustment
                  bounded to [AUTOFIX_THRESHOLD_MIN, AUTOFIX_THRESHOLD_MAX]
        MANUAL_REVIEW: lower max_confidence_threshold by adjustment
                  bounded to [MANUAL_THRESHOLD_MIN, MANUAL_THRESHOLD_MAX]
        AI_REVIEW: no threshold adjustments (it's the fallback)

        Parameters
        ----------
        feedback_metrics:
            The dict at runtime.metadata["feedback_metrics"] (Phase 8 output).

        Returns
        -------
        Dict[str, CalibrationProfile] keyed by route string.
        """
        if not feedback_metrics:
            return self._default_profiles()

        acceptance = feedback_metrics.get("acceptance_rate_by_route", {})
        rejection  = feedback_metrics.get("rejection_rate_by_route", {})

        profiles: Dict[str, CalibrationProfile] = {}

        for route, target in _TARGET_ACCEPTANCE.items():
            observed_acc = float(acceptance.get(route, target))
            observed_rej = float(rejection.get(route, 0.0))

            # Compute adjustment: only tighten, never loosen in v1
            excess_rejection = observed_rej - (1.0 - target)
            if excess_rejection > 0:
                adjustment = min(self.max_adjustment, excess_rejection)
            else:
                adjustment = 0.0

            # Apply route-specific threshold logic
            if route == "auto_fix":
                calibrated_min = max(
                    _AUTOFIX_THRESHOLD_MIN,
                    min(_AUTOFIX_THRESHOLD_MAX, _DEFAULT_AUTO_FIX_THRESHOLD + adjustment)
                )
                calibrated_max = _AUTOFIX_THRESHOLD_MAX

            elif route == "manual_review":
                # Tighten = lower the upper bound (harder to qualify for manual)
                calibrated_min = _MANUAL_THRESHOLD_MIN
                calibrated_max = min(
                    _MANUAL_THRESHOLD_MAX,
                    max(_MANUAL_THRESHOLD_MIN, _DEFAULT_MANUAL_THRESHOLD - adjustment)
                )
                adjustment = 0.0  # adjustment semantics differ for manual; reset for clarity

            else:  # ai_review — fallback route, no explicit threshold
                adjustment     = 0.0
                calibrated_min = 0.0
                calibrated_max = 1.0

            profiles[route] = CalibrationProfile(
                route=route,
                target_acceptance_rate=target,
                observed_acceptance_rate=round(observed_acc, 4),
                confidence_adjustment=round(adjustment, 4),
                min_confidence_threshold=round(calibrated_min, 4),
                max_confidence_threshold=round(calibrated_max, 4),
            )

        return profiles

    def _default_profiles(self) -> Dict[str, CalibrationProfile]:
        """Return zero-adjustment profiles (used when feedback is absent)."""
        return {
            "auto_fix": CalibrationProfile(
                route="auto_fix",
                target_acceptance_rate=_TARGET_ACCEPTANCE["auto_fix"],
                observed_acceptance_rate=_TARGET_ACCEPTANCE["auto_fix"],
                confidence_adjustment=0.0,
                min_confidence_threshold=_DEFAULT_AUTO_FIX_THRESHOLD,
                max_confidence_threshold=_AUTOFIX_THRESHOLD_MAX,
            ),
            "ai_review": CalibrationProfile(
                route="ai_review",
                target_acceptance_rate=_TARGET_ACCEPTANCE["ai_review"],
                observed_acceptance_rate=_TARGET_ACCEPTANCE["ai_review"],
                confidence_adjustment=0.0,
                min_confidence_threshold=0.0,
                max_confidence_threshold=1.0,
            ),
            "manual_review": CalibrationProfile(
                route="manual_review",
                target_acceptance_rate=_TARGET_ACCEPTANCE["manual_review"],
                observed_acceptance_rate=_TARGET_ACCEPTANCE["manual_review"],
                confidence_adjustment=0.0,
                min_confidence_threshold=_MANUAL_THRESHOLD_MIN,
                max_confidence_threshold=_DEFAULT_MANUAL_THRESHOLD,
            ),
        }

    # ------------------------------------------------------------------
    # Route calibration
    # ------------------------------------------------------------------

    def calibrate_route(
        self,
        route: Any,
        confidence: float,
        is_simple_fix: bool,
        profiles: Dict[str, CalibrationProfile],
    ) -> Any:
        """Apply calibrated threshold override to an already-assigned route.

        Modes
        -----
        shadow  — observe only, return original route unchanged.
        suggest — compute override, log it, but still return original route.
        enforce — compute override and return it (may downgrade auto_fix → ai_review).

        Parameters are the same as _apply_threshold_override().
        """
        if self.mode == "shadow":
            return route  # observe only

        overridden = _apply_threshold_override(route, confidence, is_simple_fix, profiles)

        if self.mode == "suggest":
            if overridden != route:
                logger.info(
                    "CALIBRATION SUGGEST: route=%r would become %r "
                    "(confidence=%.3f, is_simple_fix=%s)",
                    str(route), str(overridden), confidence, is_simple_fix,
                )
            return route  # suggestion logged, no actual change

        # mode == "enforce"
        if overridden != route:
            logger.debug(
                "CALIBRATION ENFORCE: %r → %r (confidence=%.3f, is_simple_fix=%s)",
                str(route), str(overridden), confidence, is_simple_fix,
            )
        return overridden

    # ------------------------------------------------------------------
    # Metadata storage
    # ------------------------------------------------------------------

    def store_calibration_metrics(
        self,
        runtime: object,
        profiles: Dict[str, CalibrationProfile],
    ) -> None:
        """Inject calibration summary into runtime.metadata['calibration_metrics']."""
        try:
            if not hasattr(runtime, "metadata"):
                return
            runtime.metadata["calibration_metrics"] = {
                "mode": self.mode,
                "max_adjustment_per_run": self.max_adjustment,
                "thresholds": {
                    r: {"min": p.min_confidence_threshold, "max": p.max_confidence_threshold}
                    for r, p in profiles.items()
                },
                "adjustments": {
                    r: p.confidence_adjustment for r, p in profiles.items()
                },
                "profiles": {
                    r: {
                        "target_acceptance_rate":   p.target_acceptance_rate,
                        "observed_acceptance_rate": p.observed_acceptance_rate,
                        "confidence_adjustment":    p.confidence_adjustment,
                    }
                    for r, p in profiles.items()
                },
            }
        except Exception:
            pass  # best-effort, never affects pipeline
