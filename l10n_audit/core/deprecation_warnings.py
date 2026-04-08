"""
Phase G1 — Runtime Deprecation Warning System

Provides deterministic tracking and structured warning logic
for legacy artifact accesses. Ensures zero regressions by using ONLY logger.debug,
preventing noisy production logs. Supports an optional "strict_mode" which
promotes warnings to RuntimeErrors for CI/CD governance.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from l10n_audit.core.deprecation_registry import get_by_name, get_governance_classification

logger = logging.getLogger(__name__)

# Global tracking dict for Phase G1:
# { artifact_name: { "read_count": X, "write_count": Y } }
_USAGE_TRACKING: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"read_count": 0, "write_count": 0})


def get_usage_tracking() -> dict[str, dict[str, int]]:
    """Return a snapshot of current runtime usage counts."""
    return dict(_USAGE_TRACKING)


def warn_deprecated_artifact(
    artifact_name: str,
    path: Path | str,
    action: str,  # 'read' or 'write'
    strict_mode: bool = False,
):
    """
    Emit a structured deprecation warning (or RuntimeError in strict mode)
    when a classified legacy artifact is used.
    """
    entry = get_by_name(artifact_name)
    if not entry:
        # If it's not even registered, log a trace and do nothing else
        logger.debug(f"[DEPRECATION] Unregistered artifact used [{action}]: {path}")
        return

    governance = get_governance_classification(artifact_name)

    # 1) Increment counters
    if action == "read":
        _USAGE_TRACKING[artifact_name]["read_count"] += 1
    elif action == "write":
        _USAGE_TRACKING[artifact_name]["write_count"] += 1

    # 2) Emit warning message via logger.debug
    msg = (
        f"[DEPRECATION] {entry.name} is in {entry.classification} mode.\n"
        f"Governance: {governance or 'unclassified'}\n"
        f"Action: {action.upper()}\n"
        f"Path: {path}\n"
        f"Reason: {entry.deprecation_note or ('Replace with ' + entry.replacement)}"
    )
    logger.debug(msg)

    # 3) Strict mode enforcement
    if strict_mode and governance in {"compatibility_only", "deprecated_candidate"}:
        raise RuntimeError(f"Strict Mode Violation: Deprecated artifact used.\n{msg}")
