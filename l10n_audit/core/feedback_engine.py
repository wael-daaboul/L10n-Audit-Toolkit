"""
l10n_audit/core/feedback_engine.py
====================================
Phase 8 — Feedback & Learning Loop (Observational Layer).

This module collects execution signals from pipeline Apply stages and
aggregates them for analysis. It does NOT modify any routing, enforcement,
or decision logic. It is strictly observational.

Design constraints
------------------
* Does NOT read from or write to decision_engine.py
* Does NOT modify enforcement_layer.py behavior
* Does NOT alter any file outputs, CLI behavior, or output ordering
* All operations are additive — signals are accumulated, never acted upon
* Thread-safe for future extension but not required in current scope
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict, List


# ---------------------------------------------------------------------------
# Feedback Signal
# ---------------------------------------------------------------------------

@dataclass
class FeedbackSignal:
    """A single execution outcome signal captured from an Apply stage.

    Fields
    ------
    route:
        The routing decision assigned by the Decision Engine
        (e.g. "auto_fix", "ai_review", "manual_review").
    confidence:
        The confidence score from the Decision Engine at routing time.
        Defaults to 0.5 when not present (legacy issues).
    risk:
        The risk classification from the Decision Engine at routing time.
        Defaults to "low" when not present (legacy issues).
    was_accepted:
        True if the fix was applied without modification.
    was_modified:
        True if the fix value was changed by a human reviewer before applying.
    was_rejected:
        True if the fix was skipped or rejected entirely.
    source:
        The pipeline stage that produced this signal.
        One of: "autofix" | "ai" | "manual"
    """
    route: str
    confidence: float
    risk: str

    was_accepted: bool
    was_modified: bool
    was_rejected: bool

    source: str  # "ai" | "autofix" | "manual"


# ---------------------------------------------------------------------------
# Feedback Aggregator
# ---------------------------------------------------------------------------

class FeedbackAggregator:
    """Collects FeedbackSignal instances and produces observability summaries.

    This class is strictly analytical. It never modifies routing or enforcement.
    It is designed to be instantiated per pipeline run and its output injected
    into runtime.metadata["feedback_metrics"] at the end of the run.
    """

    def __init__(self) -> None:
        self.signals: List[FeedbackSignal] = []

    def record(self, signal: FeedbackSignal) -> None:
        """Append a feedback signal to the collection."""
        self.signals.append(signal)

    def summarize(self) -> dict:
        """Produce an analytical summary of collected signals.

        Returns a dict containing:
        - total_signals: int
        - acceptance_rate_by_route: {route: float}
        - rejection_rate_by_route: {route: float}
        - avg_confidence_by_route: {route: float}
        - risk_vs_rejection: {risk_level: {rejected: int, total: int}}
        - signals_by_source: {source: int}

        All rates are floats in [0.0, 1.0]. Routes with zero signals
        are omitted from rate dicts to avoid division noise.
        """
        if not self.signals:
            return {
                "total_signals": 0,
                "acceptance_rate_by_route": {},
                "rejection_rate_by_route": {},
                "avg_confidence_by_route": {},
                "risk_vs_rejection": {},
                "signals_by_source": {},
            }

        # Accumulators
        by_route_total: Dict[str, int] = defaultdict(int)
        by_route_accepted: Dict[str, int] = defaultdict(int)
        by_route_rejected: Dict[str, int] = defaultdict(int)
        by_route_confidence: Dict[str, float] = defaultdict(float)
        by_risk_total: Dict[str, int] = defaultdict(int)
        by_risk_rejected: Dict[str, int] = defaultdict(int)
        by_source: Dict[str, int] = defaultdict(int)

        for s in self.signals:
            route = s.route or "unknown"
            by_route_total[route] += 1
            by_route_confidence[route] += s.confidence
            by_source[s.source] += 1

            if s.was_accepted:
                by_route_accepted[route] += 1
            if s.was_rejected:
                by_route_rejected[route] += 1

            risk = s.risk or "unknown"
            by_risk_total[risk] += 1
            if s.was_rejected:
                by_risk_rejected[risk] += 1

        acceptance_rate: Dict[str, float] = {}
        rejection_rate: Dict[str, float] = {}
        avg_confidence: Dict[str, float] = {}

        for route, total in by_route_total.items():
            acceptance_rate[route] = round(by_route_accepted[route] / total, 4)
            rejection_rate[route] = round(by_route_rejected[route] / total, 4)
            avg_confidence[route] = round(by_route_confidence[route] / total, 4)

        risk_vs_rejection: Dict[str, dict] = {}
        for risk, total in by_risk_total.items():
            risk_vs_rejection[risk] = {
                "total": total,
                "rejected": by_risk_rejected[risk],
                "rejection_rate": round(by_risk_rejected[risk] / total, 4),
            }

        return {
            "total_signals": len(self.signals),
            "acceptance_rate_by_route": dict(acceptance_rate),
            "rejection_rate_by_route": dict(rejection_rate),
            "avg_confidence_by_route": dict(avg_confidence),
            "risk_vs_rejection": risk_vs_rejection,
            "signals_by_source": dict(by_source),
        }
