#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
artifact_resolver.py — Phase B

Centralised read-only artifact path resolution for the L10n Audit Toolkit.

Resolution priority for every artifact key:
  1. audit_master.json → artifacts registry  (if master exists and key is populated)
  2. runtime.results_dir / <conventional relative path>
  3. explicit fallback default passed by the caller
  4. raise KeyError only when the caller asks for strict=True

Design rules:
  - NEVER creates files
  - NEVER mutates any data structure
  - ALWAYS falls back gracefully
  - Returns Path objects (resolved / absolute-safe)
  - No dependency on non-stdlib outside l10n_audit.core
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("l10n_audit.artifact_resolver")

# ---------------------------------------------------------------------------
# Conventional relative paths (the "schema" for Results/ layout)
# These are the only place in the codebase where conventional paths live.
# ---------------------------------------------------------------------------
_CONVENTIONS: dict[str, str] = {
    # User-facing and master outputs (unchanged)
    "review_queue_xlsx_path":      "review/review_queue.xlsx",
    "review_projection_xlsx_path": "review/review_projection.xlsx",
    "review_projection_json_path": "review/review_projection.json",
    
    # Machine-consumer review artifacts (Phase 9)
    "review_machine_queue_json_path": "review/review_machine_queue.json",
    
    # Legacy / Compatibility aliases
    "review_queue_json_path":      "review/review_queue.json",
    
    "aggregated_issues_path":      "normalized/aggregated_issues.json",
    "final_report_json_path":    "final/final_audit_report.json",
    "final_report_md_path":      "final/final_audit_report.md",
    "final_report_en_md_path":   "final/final_audit_report_en.md",
    "final_report_ar_md_path":   "final/final_audit_report_ar.md",
    "master_path":               "artifacts/audit_master.json",
    "final_locale_path":         "final_locale",
    
    # Phase C: Internal/transient artifacts (moved to .cache)
    "fix_plan_path":             ".cache/apply/fix_plan.json",
    "fix_plan_xlsx_path":        ".cache/apply/fix_plan.xlsx",
    "ar_fixed_json_path":        ".cache/apply/ar.fixed.json",
    "raw_reports_root":          ".cache/raw_tools",
}

# Phase C: Legacy fallback paths mapping
_LEGACY_FALLBACKS: dict[str, str] = {
    "fix_plan_path":             "fixes/fix_plan.json",
    "fix_plan_xlsx_path":        "fixes/fix_plan.xlsx",
    "ar_fixed_json_path":        "fixes/ar.fixed.json",
    "raw_reports_root":          "per_tool",
}


# ---------------------------------------------------------------------------
# load_master_artifacts
# ---------------------------------------------------------------------------

def load_master_artifacts(results_dir: Path) -> dict[str, Any]:
    """Safely load the ``artifacts`` registry from ``audit_master.json``.

    Returns an empty dict when:
    - the master file is absent
    - the file contains invalid JSON
    - the ``artifacts`` key is missing or not a dict
    """
    master_path = results_dir / "artifacts" / "audit_master.json"
    if not master_path.exists():
        return {}
    try:
        data = json.loads(master_path.read_text(encoding="utf-8"))
        reg = data.get("artifacts", {})
        if not isinstance(reg, dict):
            return {}
        return reg
    except Exception as exc:
        logger.debug("artifact_resolver: failed to read master artifacts registry: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# resolve_artifact_path  (core resolver)
# ---------------------------------------------------------------------------

def resolve_artifact_path(
    runtime,
    artifact_key: str,
    default: str | None = None,
    *,
    strict: bool = False,
) -> Path:
    """Resolve a canonical artifact path for ``artifact_key``.

    Resolution order
    ----------------
    1. ``audit_master.json`` artifacts registry entry (relative to project_root)
    2. ``runtime.results_dir`` + conventional relative path for the key
    3. ``default`` argument (treated as a path string)
    4. Raise ``KeyError`` only when ``strict=True``; otherwise returns the
       conventional path even if the file does not yet exist.

    Parameters
    ----------
    runtime:
        AuditRuntime-like object; must have ``.results_dir`` and
        ``.project_root`` attributes.
    artifact_key:
        One of the canonical keys defined in ``_CONVENTIONS``.
    default:
        Optional path string to use as last resort before raising.
    strict:
        If True and no path can be resolved, raise KeyError.
    """
    results_dir: Path = runtime.results_dir

    # 1. Try master registry (paths stored as project-root-relative strings)
    try:
        registry = load_master_artifacts(results_dir)
        reg_value = registry.get(artifact_key)
        if reg_value and str(reg_value).strip():
            # Stored as relative path → make absolute via project_root
            candidate = Path(runtime.project_root) / reg_value
            logger.debug(
                "artifact_resolver: resolved %r from master registry → %s",
                artifact_key, candidate,
            )
            return candidate
    except Exception as exc:
        logger.debug("artifact_resolver: master registry lookup failed: %s", exc)

    # 2. Conventional relative path
    convention = _CONVENTIONS.get(artifact_key)
    if convention:
        candidate = results_dir / convention
        
        # Phase C: Check legacy fallback for reads during transition
        legacy_rel = _LEGACY_FALLBACKS.get(artifact_key)
        if legacy_rel:
            legacy_path = results_dir / legacy_rel
            # If candidate doesn't exist but legacy does, return legacy path
            # Otherwise we return the candidate (which becomes the write destination if neither exists)
            if not candidate.exists() and legacy_path.exists():
                logger.debug(
                    "artifact_resolver: falling back to legacy path for %r → %s",
                    artifact_key, legacy_path,
                )
                from l10n_audit.core.deprecation_warnings import warn_deprecated_artifact
                strict = getattr(getattr(runtime, "options", None), "strict_deprecations", False)
                reg_name = "fixes_legacy_dir" if "fixes/" in legacy_rel else "per_tool_json"
                warn_deprecated_artifact(reg_name, legacy_path, "read", strict_mode=strict)
                
                return legacy_path

        logger.debug(
            "artifact_resolver: resolved %r via convention → %s",
            artifact_key, candidate,
        )
        return candidate

    # 3. Caller-supplied default
    if default is not None:
        logger.debug(
            "artifact_resolver: resolved %r via caller default → %s",
            artifact_key, default,
        )
        return Path(default)

    # 4. Strict failure
    if strict:
        raise KeyError(
            f"artifact_resolver: cannot resolve unknown artifact key {artifact_key!r} "
            f"and no default was provided."
        )

    # Non-strict: return a best-effort path so callers never crash
    logger.warning(
        "artifact_resolver: unknown key %r, returning results_dir as last resort.",
        artifact_key,
    )
    return results_dir


# ---------------------------------------------------------------------------
# Convenience wrappers (typed, documented, zero-surprise)
# ---------------------------------------------------------------------------

def resolve_review_queue_path(runtime) -> Path:
    """Resolve the primary review queue XLSX path.

    Falls back to the legacy fixed location; always returns a Path even
    when the file does not yet exist so callers can check ``.exists()``.
    """
    return resolve_artifact_path(runtime, "review_queue_xlsx_path")


def resolve_review_queue_json_path(runtime) -> Path:
    """Resolve the legacy JSON mirror of the review queue.
    
    [DEPRECATED] Use resolve_review_machine_queue_json_path for machine consumers
    or resolve_review_projection_json_path for reporting.
    """
    return resolve_artifact_path(runtime, "review_queue_json_path")


def resolve_review_machine_queue_json_path(runtime) -> Path:
    """Resolve the primary machine-consumer JSON artifact (Phase 9)."""
    return resolve_artifact_path(runtime, "review_machine_queue_json_path")


def resolve_review_projection_path(runtime) -> Path:
    """Resolve the analytical review projection XLSX path."""
    return resolve_artifact_path(runtime, "review_projection_xlsx_path")


def resolve_review_projection_json_path(runtime) -> Path:
    """Resolve the analytical review projection JSON path."""
    return resolve_artifact_path(runtime, "review_projection_json_path")


def resolve_aggregated_issues_path(runtime) -> Path:
    """Resolve ``normalized/aggregated_issues.json``."""
    return resolve_artifact_path(runtime, "aggregated_issues_path")


def resolve_final_report_path(runtime) -> Path:
    """Resolve ``final/final_audit_report.json``."""
    return resolve_artifact_path(runtime, "final_report_json_path")


def resolve_fix_plan_path(runtime) -> Path:
    """Resolve ``fixes/fix_plan.json``."""
    return resolve_artifact_path(runtime, "fix_plan_path")


def resolve_master_path(runtime) -> Path:
    """Resolve ``artifacts/audit_master.json``."""
    return resolve_artifact_path(runtime, "master_path")


def resolve_ar_fixed_json_path(runtime) -> Path:
    """Resolve ``fixes/ar.fixed.json`` (output of apply)."""
    return resolve_artifact_path(runtime, "ar_fixed_json_path")
