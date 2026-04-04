"""
Phase E — Legacy Artifact Deprecation Registry
===============================================

This module is the authoritative governance record for all artifact paths
that were historically emitted directly by pipeline stages, and their
current classification under the master-data migration.

RULES:
- This registry is READ-ONLY at runtime; it does NOT control write paths.
- All write-path control happens through OutputSuppression flags (Phase D).
- All read-path resolution is handled by artifact_resolver.py (Phase B/C).
- This file is the human-readable contract for decommission planning.

CLASSIFICATION LEGEND:
  active_required        — code reads it directly and no resolver fallback exists
  compatibility_required — still emitted; read only via resolver fallback or legacy consumers
  optional_legacy        — emitted only behind optional suppression flags; no mandatory consumer
  deprecated_candidate   — no active code consumer; safe to stop emitting after migration period
  do_not_touch_yet       — classification uncertain pending further evidence

WARNING STRATEGY:
  Artifacts classified "compatibility_required" or "deprecated_candidate" will
  emit a logger.debug(...) warning in the write path where applicable.
  These warnings MUST NOT alter output schemas or break tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Classification = Literal[
    "active_required",
    "compatibility_required",
    "optional_legacy",
    "deprecated_candidate",
    "do_not_touch_yet",
    "removed",
]

RemovalReadiness = Literal[
    "remove_now",
    "remove_after_migration",
    "keep",
    "warn_only",
    "removed",
]


@dataclass(frozen=True)
class ArtifactEntry:
    """A single entry in the legacy artifact deprecation registry."""

    name: str
    """Short artifact identifier."""

    path_pattern: str
    """Relative path inside Results/; use {tool} for per-tool wildcards."""

    classification: Classification
    """Current lifecycle classification."""

    removal_readiness: RemovalReadiness
    """Decommission readiness for Phase F+."""

    active_consumers: list[str]
    """Active code or CLI consumers — qualified module.function references."""

    replacement: str
    """Canonical replacement path or mechanism."""

    evidence: str
    """Audit evidence that justifies the classification."""

    deprecation_note: str = ""
    """Human note describing the deprecation plan."""

    removal_phase: str = ""
    """Documentation of which phase executed the actual removal."""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

LEGACY_ARTIFACT_REGISTRY: list[ArtifactEntry] = [

    # ── 1. audit_master.json ─────────────────────────────────────────────────
    ArtifactEntry(
        name="audit_master",
        path_pattern="artifacts/audit_master.json",
        classification="active_required",
        removal_readiness="keep",
        active_consumers=[
            "artifact_resolver.load_master_artifacts",
            "artifact_resolver.resolve_artifact_path (priority lookup)",
            "report_aggregator.load_from_master",
            "report_aggregator.write_audit_master",
            "apply_review_fixes.reconcile_master",
        ],
        replacement="self — this IS the master store",
        evidence=(
            "artifact_resolver.py lines 74, 103 reads master first. "
            "report_aggregator.py line 762 hydrates from master when no explicit report. "
            "apply_review_fixes.py line 79 reconciles post-apply state. "
            "This is the Phase 1 authoritative source."
        ),
        deprecation_note="Never deprecate. Central authoritative artifact.",
    ),

    # ── 2. review/review_queue.xlsx ──────────────────────────────────────────
    ArtifactEntry(
        name="review_queue_xlsx",
        path_pattern="review/review_queue.xlsx",
        classification="active_required",
        removal_readiness="keep",
        active_consumers=[
            "apply_review_fixes.main (CLI --review-queue default)",
            "cli.py line 333 (apply subcommand default)",
            "api.py line 297 (returned as API artifact)",
            "tests/test_safe_fixes.py (multiple test fixtures)",
        ],
        replacement="self — XLSX is the human-edit contract surface for apply",
        evidence=(
            "cli.py line 333: default path for apply --review-queue. "
            "apply_review_fixes.py line 330: CLI default. "
            "api.py line 297: returned in report artifact list. "
            "6 test fixtures in test_safe_fixes.py read this path directly."
        ),
        deprecation_note="Never deprecate. Core user-facing contract for apply workflow.",
    ),

    # ── 3. review/review_queue.json ──────────────────────────────────────────
    ArtifactEntry(
        name="review_queue_json",
        path_pattern="review/review_queue.json",
        classification="active_required",
        removal_readiness="keep",
        active_consumers=[
            "ai_review.load_issues (line 28): fallback when final_audit_report.json absent",
            "report_aggregator run_stage (line 857): always written",
            "artifact_resolver.resolve_review_queue_path",
            "audit_master.json artifacts registry entry",
        ],
        replacement="audit_master.json[review_projection] for machine consumers",
        evidence=(
            "ai_review.py line 28: reads review_queue.json when final report absent. "
            "This is a first-class fallback for the ai-review stage. "
            "Removing would break ai-review when reports stage hasn't run yet."
        ),
        deprecation_note=(
            "Technically: review_queue.json could be replaced by master hydration in ai_review.py. "
            "However it is an active fallback for the ai-review consumer. "
            "Classify as keep for now; demote to warn_only after ai_review migrates to master."
        ),
    ),

    # ── 4. final/final_audit_report.json ─────────────────────────────────────
    ArtifactEntry(
        name="final_audit_report_json",
        path_pattern="final/final_audit_report.json",
        classification="active_required",
        removal_readiness="keep",
        active_consumers=[
            "ai_review.load_issues (line 26): primary load path",
            "api.py line 269-273: read for consumer stage validation",
            "audit_report_utils.load_single_report (line 414): --input-report path",
            "schema_validation.py line 115: schema checked against this path",
            "tests/test_cli_workspace.py line 64: asserted present",
        ],
        replacement="audit_master.json[legacy_artifacts] for future replay",
        evidence=(
            "ai_review.py line 26: this is the PRIMARY issue source for AI review. "
            "api.py line 269: read for consumer-stage validation guard. "
            "audit_report_utils.py line 414: load_single_report reads it for --input-report. "
            "schema_validation.py line 115: validated against schema. "
            "Must remain."
        ),
        deprecation_note="Never deprecate until ai_review migrates to master-hydration path.",
    ),

    # ── 5. final/final_audit_report.md ───────────────────────────────────────
    ArtifactEntry(
        name="final_audit_report_md",
        path_pattern="final/final_audit_report.md",
        classification="active_required",
        removal_readiness="keep",
        active_consumers=[
            "report_aggregator run_stage (line 854): always written",
            "report_aggregator markdown (line 262): referenced in dashboard comment",
            "CLI help text and docs/output_reports.md",
        ],
        replacement="self — primary human-readable report",
        evidence=(
            "report_aggregator.py line 262 shows this as the dashboard path. "
            "report_aggregator.py line 854: not behind any suppression flag. "
            "Primary deliverable for humans."
        ),
        deprecation_note="Never deprecate. Primary human-readable output.",
    ),

    # ── 6. final/final_audit_report_en.md ─────────────────────────────────── 
    ArtifactEntry(
        name="final_audit_report_en_md",
        path_pattern="final/final_audit_report_en.md",
        classification="removed",
        removal_readiness="removed",
        active_consumers=[],
        replacement="final/final_audit_report.md (identical content currently)",
        evidence=(
            "Removed in Phase G2. Write paths deleted from report_aggregator.py. "
            "Dead flags cleared in Phase G3."
        ),
        deprecation_note=(
            "Actually removed entirely."
        ),
        removal_phase="G2",
    ),

    # ── 7. final/final_audit_report_ar.md ─────────────────────────────────── 
    ArtifactEntry(
        name="final_audit_report_ar_md",
        path_pattern="final/final_audit_report_ar.md",
        classification="removed",
        removal_readiness="removed",
        active_consumers=[],
        replacement="final/final_audit_report.md (identical content currently)",
        evidence=(
            "Removed in Phase G2 along with _en variant."
        ),
        deprecation_note=(
            "Actually removed entirely."
        ),
        removal_phase="G2",
    ),

    # ── 8. normalized/aggregated_issues.json ─────────────────────────────────
    ArtifactEntry(
        name="aggregated_issues_json",
        path_pattern="normalized/aggregated_issues.json",
        classification="compatibility_required",
        removal_readiness="warn_only",
        active_consumers=[
            "artifact_resolver.resolve_aggregated_issues_path (resolver only)",
            "report_aggregator.write_audit_master (records path in registry)",
        ],
        replacement="audit_master.json[issue_inventory] — contains full issue list",
        evidence=(
            "artifact_resolver.py line 203: resolve_aggregated_issues_path exists but is NOT "
            "called in any active read path in production code — only registers in master. "
            "report_aggregator.py line 865: written always, registered in master registry. "
            "No test reads this file directly (test grep returned 0 results). "
            "audit_master.json already contains the full issue_inventory as replacement."
        ),
        deprecation_note=(
            "This file is written for historical compatibility and resolver registration. "
            "No active code reads it directly — audit_master.json is the replacement. "
            "Phase F candidate: add deprecation warning on write, then stop emitting."
        ),
    ),

    # ── 9. per_tool/*/*.json (raw tool reports) ───────────────────────────────
    ArtifactEntry(
        name="per_tool_json",
        path_pattern="per_tool/{tool}/{tool}_report.json",
        classification="compatibility_required",
        removal_readiness="warn_only",
        active_consumers=[
            "context_evaluator.load_en_languagetool_signals (line 135): fallback if .cache absent",
            "audit_report_utils.load_all_report_issues (line 398): fallback path",
            "artifact_resolver._LEGACY_FALLBACKS: explicitly mapped",
            "tests/test_report_aggregator.py: fixtures write to per_tool/",
            "tests/test_report_dx_upgrades.py line 80: fixture writes to per_tool/",
        ],
        replacement=".cache/raw_tools/{tool}/{tool}_report.json",
        evidence=(
            "Phase C: new writes go to .cache/raw_tools/. "
            "context_evaluator.py line 135: has explicit fallback to per_tool/ if .cache absent. "
            "audit_report_utils.py line 398: fallback reads from per_tool/. "
            "Tests still write fixtures to per_tool/ — these tests verify fallback compatibility. "
            "Must remain fallback-readable for tests to pass."
        ),
        deprecation_note=(
            "Cannot remove fallback read until tests are migrated to .cache/raw_tools/ fixtures. "
            "Cannot remove per_tool/ writes since they no longer happen (Phase C moved to .cache). "
            "Legacy per_tool/ dirs populated by old runs remain readable safely. "
            "Phase F: migrate test fixtures to .cache/raw_tools/, then remove fallback logic."
        ),
    ),

    # ── 10. per_tool/*/*.csv  ─────────────────────────────────────────────────
    ArtifactEntry(
        name="per_tool_csv",
        path_pattern=".cache/raw_tools/{tool}/{tool}_report.csv",
        classification="optional_legacy",
        removal_readiness="warn_only",
        active_consumers=[],
        replacement="None — no downstream code reads tool CSVs",
        evidence=(
            "grep across all .py files: zero readers of *.csv in per_tool or raw_tools. "
            "Phase D: behind options.suppression.include_per_tool_csv flag. "
            "Human-access only artifact (Excel/spreadsheet consumers). "
            "No test asserts CSV presence."
        ),
        deprecation_note=(
            "Safe to suppress immediately via include_per_tool_csv=False. "
            "Phase F candidate: set default to False."
        ),
    ),

    # ── 11. per_tool/*/*.xlsx ─────────────────────────────────────────────────
    ArtifactEntry(
        name="per_tool_xlsx",
        path_pattern=".cache/raw_tools/{tool}/{tool}_report.xlsx",
        classification="optional_legacy",
        removal_readiness="warn_only",
        active_consumers=[],
        replacement="None — no downstream code reads tool XLSXs",
        evidence=(
            "grep across all .py files: zero readers of tool-level XLSX files. "
            "Phase D: behind options.suppression.include_per_tool_xlsx flag. "
            "Human-access only. No test asserts XLSX presence."
        ),
        deprecation_note=(
            "Safe to suppress via include_per_tool_xlsx=False. "
            "Phase F candidate: set default to False."
        ),
    ),

    # ── 12. .cache/apply/fix_plan.xlsx ───────────────────────────────────────
    ArtifactEntry(
        name="fix_plan_xlsx",
        path_pattern=".cache/apply/fix_plan.xlsx",
        classification="optional_legacy",
        removal_readiness="warn_only",
        active_consumers=[],
        replacement=".cache/apply/fix_plan.json (machine-readable equivalent)",
        evidence=(
            "artifact_resolver.py line 48: registered but no production code reads it. "
            "Phase D: behind options.suppression.include_fix_plan_xlsx flag. "
            "fix_plan.json (always written) is the machine-readable canonical form. "
            "XLSX is human-review convenience only."
        ),
        deprecation_note=(
            "Safe to suppress via include_fix_plan_xlsx=False. "
            "Phase F candidate: change default to False."
        ),
    ),

    # ── 13. fixes/ legacy directory (old write path) ─────────────────────────
    ArtifactEntry(
        name="fixes_legacy_dir",
        path_pattern="fixes/fix_plan.json",
        classification="deprecated_candidate",
        removal_readiness="warn_only",
        active_consumers=[
            "artifact_resolver._LEGACY_FALLBACKS (line 55-57): read fallback only",
        ],
        replacement=".cache/apply/fix_plan.json",
        evidence=(
            "Phase C moved all apply writes to .cache/apply/. "
            "artifact_resolver._LEGACY_FALLBACKS still reads from fixes/ if .cache absent. "
            "No production code writes to fixes/ any more. "
            "If .cache/apply/ exists (always true on fresh run), fixes/ is never read."
        ),
        deprecation_note=(
            "The fixes/ directory is only populated by pre-Phase-C runs. "
            "On any fresh pipeline run, .cache/apply/ is populated and fixes/ is never consulted. "
            "Phase F: remove _LEGACY_FALLBACKS entry for fix_plan_path/fix_plan_xlsx_path/ar_fixed_json_path "
            "after confirming no active deployment has a pre-Phase-C fixes/ dir as primary source."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Convenience lookups
# ---------------------------------------------------------------------------

def get_by_classification(classification: Classification) -> list[ArtifactEntry]:
    """Return all registry entries with the given classification."""
    return [entry for entry in LEGACY_ARTIFACT_REGISTRY if entry.classification == classification]


def get_by_name(name: str) -> ArtifactEntry | None:
    """Look up a single registry entry by artifact name."""
    for entry in LEGACY_ARTIFACT_REGISTRY:
        if entry.name == name:
            return entry
    return None


def summary_dict() -> dict:
    """Produce a JSON-serializable summary of the registry for embedding in audit_master."""
    return {
        "schema_version": "phase_E_v1",
        "total": len(LEGACY_ARTIFACT_REGISTRY),
        "by_classification": {
            classification: [e.name for e in get_by_classification(classification)]  # type: ignore[arg-type]
            for classification in (
                "active_required",
                "compatibility_required",
                "optional_legacy",
                "deprecated_candidate",
                "do_not_touch_yet",
                "removed",
            )
        },
        "entries": [
            {
                "name": e.name,
                "path_pattern": e.path_pattern,
                "classification": e.classification,
                "removal_readiness": e.removal_readiness,
                "replacement": e.replacement,
                "deprecation_note": e.deprecation_note,
                "removal_phase": e.removal_phase,
            }
            for e in LEGACY_ARTIFACT_REGISTRY
        ],
    }
