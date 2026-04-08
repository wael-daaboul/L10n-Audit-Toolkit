from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict

@dataclass
class RoutingMetrics:
    total: int = 0
    by_route: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    would_skip_autofix: int = 0
    would_skip_ai: int = 0
    total_confidence: float = 0.0
    count_by_risk: Dict[str, int] = field(default_factory=lambda: {"low": 0, "medium": 0, "high": 0})
    # Phase 12 — context adjustment counters
    context_adjusted_count: int = 0
    context_downgrade_count: int = 0
    context_override_manual_count: int = 0
    decision_explanations_emitted: int = 0
    calibration_route_changes: int = 0
    context_route_changes: int = 0

    def record(self, route: str) -> None:
        self.total += 1
        self.by_route[route] += 1

    def record_autofix_skip(self) -> None:
        self.would_skip_autofix += 1

    def record_ai_skip(self) -> None:
        self.would_skip_ai += 1

    def record_adaptive(self, confidence: float, risk: str) -> None:
        self.total_confidence += confidence
        if risk not in self.count_by_risk:
            self.count_by_risk[risk] = 0
        self.count_by_risk[risk] += 1

    def record_context_adjustment(self, rules_triggered: list[str], route_changed: bool = False) -> None:
        """Record Phase 12 context adjustment metrics."""
        if not rules_triggered:
            return
        self.context_adjusted_count += 1
        if route_changed:
            self.context_route_changes += 1
        if "risk_downgrade" in rules_triggered:
            self.context_downgrade_count += 1
        if "manual_override" in rules_triggered:
            self.context_override_manual_count += 1

    def record_decision_explanation(self) -> None:
        self.decision_explanations_emitted += 1

    def record_calibration_route_change(self) -> None:
        self.calibration_route_changes += 1

    def to_dict(self) -> dict:
        avg_conf = round(self.total_confidence / max(1, self.total), 4)
        return {
            "total": self.total,
            "by_route": dict(self.by_route),
            "would_skip_autofix": self.would_skip_autofix,
            "would_skip_ai": self.would_skip_ai,
            "average_confidence": avg_conf,
            "count_by_risk_level": dict(self.count_by_risk),
            # Phase 12
            "context_adjusted_count": self.context_adjusted_count,
            "context_downgrade_count": self.context_downgrade_count,
            "context_override_manual_count": self.context_override_manual_count,
            "decision_explanations_emitted": self.decision_explanations_emitted,
            "calibration_route_changes": self.calibration_route_changes,
            "context_route_changes": self.context_route_changes,
        }


def enrich_with_decision_quality(metrics: dict, decision_quality_summary: dict) -> dict:
    """Attach decision quality summary additively without changing the base shape."""
    enriched = dict(metrics)
    enriched["decision_quality"] = dict(decision_quality_summary)
    return enriched
