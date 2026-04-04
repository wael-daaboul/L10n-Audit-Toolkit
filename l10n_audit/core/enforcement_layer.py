import logging
from typing import Any, Dict

from l10n_audit.core.decision_engine import is_routing_enabled

logger = logging.getLogger("l10n_audit.enforcement")

class UnifiedRoutingMetrics:
    def __init__(self) -> None:
        self.total = 0
        self.by_route: Dict[str, int] = {}
        self.skipped_ai = 0
        self.skipped_autofix = 0
        self.total_confidence: float = 0.0
        self.count_by_risk: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}

    def record(self, route: str) -> None:
        self.total += 1
        current = self.by_route.get(route, 0)
        self.by_route[route] = current + 1

    def record_skip(self, stage: str) -> None:
        if stage == "ai":
            self.skipped_ai += 1
        elif stage == "autofix":
            self.skipped_autofix += 1

    def record_adaptive(self, confidence: float, risk: str) -> None:
        self.total_confidence += confidence
        if risk not in self.count_by_risk:
            self.count_by_risk[risk] = 0
        self.count_by_risk[risk] += 1

    def to_dict(self) -> Dict[str, Any]:
        avg_conf = round(self.total_confidence / max(1, self.total), 4)
        return {
            "total": self.total,
            "by_route": self.by_route,
            "skipped_ai": self.skipped_ai,
            "skipped_autofix": self.skipped_autofix,
            "average_confidence": avg_conf,
            "count_by_risk_level": self.count_by_risk,
            # Legacy fields for backward compatibility with existing tests
            "would_skip_ai": self.skipped_ai,
            "would_skip_autofix": self.skipped_autofix,
        }

class EnforcementController:
    def __init__(self, runtime: Any) -> None:
        self.enabled = is_routing_enabled(runtime)
        self.metrics = UnifiedRoutingMetrics()

    def should_process(self, route: str | None, stage: str) -> bool:
        """
        Determines if a finding should be processed in the given stage based on its route.
        Fallback legacy cases (route is None) are always approved to avoid backward compatibility issues.
        If routing is disabled globally, all findings are processed.
        """
        if not self.enabled:
            return True

        # Legacy fallback
        if route is None:
            if stage == "ai":
                route = "ai_review"
            elif stage == "autofix":
                route = "auto_fix"

        if stage == "ai":
            return route == "ai_review"
        elif stage == "autofix":
            return route == "auto_fix"

        return True

    def record(self, route: str | None) -> None:
        # Avoid recording None if they fall back, though decision_engine explicitly sets 'unknown' if not mapped
        normalized_route = route if route is not None else "unknown"
        self.metrics.record(normalized_route)

    def record_adaptive(self, confidence: float, risk: str) -> None:
        self.metrics.record_adaptive(confidence, risk)

    def record_skip(self, stage: str) -> None:
        self.metrics.record_skip(stage)

    def save_metrics(self, runtime: Any) -> None:
        if not self.enabled:
            return
            
        try:
            if hasattr(runtime, "metadata"):
                # Use unified key, but also expose the aliases for backward compatibility if needed by older tests
                runtime.metadata["routing_metrics_unified"] = self.metrics.to_dict()
                
                # Forward-aliases to prevent breaking tests relying on old keys
                runtime.metadata["routing_metrics"] = self.metrics.to_dict()
                runtime.metadata["routing_metrics_autofix"] = self.metrics.to_dict()
        except Exception as e:
            logger.debug("Failed to save unified metrics: %s", e)
