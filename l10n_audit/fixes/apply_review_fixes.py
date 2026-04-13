#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json as _json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from l10n_audit.core.audit_runtime import AuditRuntimeError, compute_text_hash, load_locale_mapping, load_runtime, read_simple_xlsx, write_json
from l10n_audit.core.artifact_resolver import (
    resolve_ar_fixed_json_path, 
    resolve_fix_plan_path, 
    resolve_master_path,
    resolve_review_final_path,
)
from l10n_audit.fixes.fix_merger import FROZEN_ARTIFACT_TYPE_VALUE

logger = logging.getLogger("l10n_audit.fixes")

REQUIRED_REVIEW_COLUMNS = (
    "key",
    "locale",
    "issue_type",
    "approved_new",
    "status",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
)

# ---------------------------------------------------------------------------
# H1 Artifact Type Boundary
# ---------------------------------------------------------------------------
# Column that must be present and equal to FROZEN_ARTIFACT_TYPE_VALUE in every
# row of a valid frozen apply artifact (review_final.xlsx).
# review_queue.xlsx does not carry this column; apply rejects it loudly.
FROZEN_ARTIFACT_TYPE_COLUMN: str = "frozen_artifact_type"

# ---------------------------------------------------------------------------
# H6 Apply Input Contract
# ---------------------------------------------------------------------------
# Minimum required fields that apply expects to be non-empty in EVERY row of
# the frozen apply artifact.  Checked as an artifact-level pre-check before
# any per-row hash validation or write logic runs.
#
# Field rationale:
#   key               — identifies what to write in the locale file
#   locale            — identifies which locale file to write
#   approved_new      — the value to write
#   source_hash       — staleness guard (compared against live disk value)
#   suggested_hash    — tamper guard (compared against approved_new)
#   plan_id           — ties the row to a specific pipeline run
#   frozen_artifact_type — artifact-type marker (H1); must survive into apply
APPLY_REQUIRED_FIELDS: tuple[str, ...] = (
    "key",
    "locale",
    "approved_new",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "frozen_artifact_type",
)


class WrongArtifactTypeError(ValueError):
    """
    Raised when apply is given a workbook that is not a frozen apply artifact.

    This prevents review_queue.xlsx from being accidentally passed to apply.
    No row-level processing runs if this error is raised.
    """


class ApplyContractError(ValueError):
    """
    Raised when the frozen apply artifact violates the minimum execution contract.

    This is an artifact-level pre-check failure produced by H6.  It is raised
    before any per-row hash validation or write logic runs, and before any
    partial apply can occur.

    No row is applied if this error is raised.
    """


def _assert_frozen_artifact_type(rows: list[dict], xlsx_path: Path) -> None:
    """
    Validate that each row in the loaded workbook carries the frozen artifact
    type marker.  Raises WrongArtifactTypeError before any per-row apply logic
    runs if the artifact is not a valid frozen artifact.

    A workbook is accepted if ALL rows carry
    frozen_artifact_type == FROZEN_ARTIFACT_TYPE_VALUE.

    A workbook is rejected (WrongArtifactTypeError) if:
      - the frozen_artifact_type column is absent from every row, OR
      - ANY row carries a value other than FROZEN_ARTIFACT_TYPE_VALUE

    Empty workbooks (zero rows) are accepted — an empty frozen artifact is
    a valid degenerate case (all rows rejected at promotion).

    Compatibility note: frozen artifacts produced before H1 (without the column)
    will be rejected with a clear message directing the user to re-run
    prepare-apply.  There is NO silent fallback for legacy artifacts.
    """
    if not rows:
        return  # empty artifact is valid

    column_present = any(FROZEN_ARTIFACT_TYPE_COLUMN in row for row in rows)
    if not column_present:
        raise WrongArtifactTypeError(
            f"The workbook at '{xlsx_path}' is not a frozen apply artifact.\n"
            f"The '{FROZEN_ARTIFACT_TYPE_COLUMN}' column is missing from all rows.\n"
            f"If this is a review_queue.xlsx, you must run 'prepare-apply' first to produce "
            f"a frozen review_final.xlsx before running apply.\n"
            f"If this is an older review_final.xlsx (produced before H1 hardening), "
            f"re-run 'prepare-apply' to regenerate it with the artifact type marker."
        )

    # Check every row for the correct marker value
    bad_rows = [
        (i, row.get(FROZEN_ARTIFACT_TYPE_COLUMN))
        for i, row in enumerate(rows, start=2)
        if row.get(FROZEN_ARTIFACT_TYPE_COLUMN) != FROZEN_ARTIFACT_TYPE_VALUE
    ]
    if bad_rows:
        examples = ", ".join(
            f"row {r} has {v!r}" for r, v in bad_rows[:3]
        )
        raise WrongArtifactTypeError(
            f"The workbook at '{xlsx_path}' contains rows with an unexpected "
            f"frozen_artifact_type value.\n"
            f"Expected '{FROZEN_ARTIFACT_TYPE_VALUE}' in every row. {examples}.\n"
            f"Do not manually edit the frozen_artifact_type column."
        )


def _assert_apply_contract(rows: list[dict], xlsx_path: Path) -> None:
    """
    H6 — Apply input contract pre-check.

    Validates that every row in the frozen artifact carries non-empty values
    for all fields in APPLY_REQUIRED_FIELDS.  Raises ApplyContractError
    before any per-row hash validation, locale read, or write logic runs.

    This check runs AFTER _assert_frozen_artifact_type() (H1) and BEFORE
    all per-row processing.  It is an artifact-level contract gate, not a
    row-level skipper: any violation aborts the entire invocation.

    Empty workbooks (zero rows) are accepted — consistent with H1 semantics.
    """
    if not rows:
        return

    violations: list[dict] = []
    for row_num, row in enumerate(rows, start=2):
        row_violations: list[str] = []
        for field in APPLY_REQUIRED_FIELDS:
            value = row.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                row_violations.append(field)
        if row_violations:
            violations.append({
                "row": row_num,
                "key": str(row.get("key", "")),
                "locale": str(row.get("locale", "")),
                "missing_or_empty": row_violations,
            })

    if violations:
        summary = "; ".join(
            f"row {v['row']} ({v['key']!r}/{v['locale']!r}) missing {v['missing_or_empty']}"
            for v in violations[:5]  # cap error output at 5 examples
        )
        raise ApplyContractError(
            f"The frozen apply artifact at '{xlsx_path}' violates the minimum apply contract.\n"
            f"{len(violations)} row(s) have missing or empty required field(s): {summary}.\n"
            f"Re-run 'prepare-apply' to produce a valid frozen artifact.\n"
            f"Required fields: {list(APPLY_REQUIRED_FIELDS)}"
        )


def _normalized_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value.strip() else None


def _record_apply_rejection(
    runtime: object,
    row: dict,
    reason: str,
    *,
    missing_fields: list[str] | None = None,
    expected: str | None = None,
    actual: str | None = None,
) -> dict:
    rejection = {
        "key": str(row.get("key", "")),
        "locale": str(row.get("locale", "")),
        "reason": reason,
    }
    if missing_fields:
        rejection["missing_fields"] = missing_fields
    if expected is not None:
        rejection["expected"] = expected
    if actual is not None:
        rejection["actual"] = actual
    if runtime is not None and hasattr(runtime, "metadata") and isinstance(runtime.metadata, dict):
        runtime.metadata.setdefault("apply_rejections", []).append(rejection)
    else:
        logger.debug("Rejecting apply row: %s", rejection)
    return rejection


def _get_applied_suggestions_store(runtime: object) -> list[str]:
    if runtime is not None and hasattr(runtime, "metadata") and isinstance(runtime.metadata, dict):
        store = runtime.metadata.setdefault("applied_suggestions", [])
        if isinstance(store, list):
            return store
        runtime.metadata["applied_suggestions"] = list(store) if isinstance(store, (set, tuple)) else []
        return runtime.metadata["applied_suggestions"]
    return []


def _build_apply_trace_entry(
    row: dict,
    *,
    status: str,
    reason: str | None,
    decision_context: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "key": str(row.get("key", "")),
        "locale": str(row.get("locale", "")),
        "status": status,
        "reason": reason,
        "suggested_hash": str(row.get("suggested_hash", "")),
        "source_hash": str(row.get("source_hash", "")),
        "plan_id": str(row.get("plan_id", "")),
        "decision_context": decision_context or {},
    }


def _build_rejection_decision_context(
    row: dict,
    rejection: dict,
    current_value: object,
    applied_suggestions_store: list[str],
) -> dict[str, object]:
    reason = str(rejection.get("reason", ""))
    if reason == "missing_required_fields":
        return {
            "missing_fields": list(rejection.get("missing_fields", [])),
            "row_keys_present": list(row.keys()),
        }
    if reason == "source_hash_mismatch":
        runtime_value = str(current_value) if isinstance(current_value, str) else ""
        return {
            "expected_source_hash": str(rejection.get("expected", row.get("source_hash", ""))),
            "actual_current_hash": str(rejection.get("actual", compute_text_hash(runtime_value) if runtime_value else "")),
            "current_value": runtime_value,
            "source_old_value": str(row.get("source_old_value", "")),
        }
    if reason == "tampered_row_detected":
        approved_new = str(row.get("approved_new", ""))
        return {
            "approved_new": approved_new,
            "suggested_hash": str(row.get("suggested_hash", "")),
            "actual_hash": compute_text_hash(approved_new),
        }
    if reason == "duplicate_application":
        return {
            "suggested_hash": str(row.get("suggested_hash", "")),
            "already_applied_hashes": list(applied_suggestions_store),
        }
    if reason == "suggested_hash_mismatch":
        candidate_value = str(row.get("candidate_value", ""))
        return {
            "suggested_hash": str(row.get("suggested_hash", "")),
            "actual_hash": compute_text_hash(candidate_value),
            "candidate_value": candidate_value,
        }
    return {}


def _validate_apply_row(
    row: dict,
    runtime: object,
    current_value: object,
    applied_suggestions: set[str],
) -> tuple[dict[str, str] | None, dict | None]:
    key = _normalized_non_empty_string(row.get("key"))
    locale = _normalized_non_empty_string(row.get("locale"))
    current_row_value = _normalized_non_empty_string(row.get("current_value"))
    candidate_value = _normalized_non_empty_string(row.get("candidate_value"))
    source_hash = _normalized_non_empty_string(row.get("source_hash"))
    suggested_hash = _normalized_non_empty_string(row.get("suggested_hash"))

    missing_fields: list[str] = []
    if key is None:
        missing_fields.append("key")
    if locale is None:
        missing_fields.append("locale")
    if current_row_value is None:
        missing_fields.append("current_value")
    if candidate_value is None:
        missing_fields.append("candidate_value")
    if source_hash is None:
        missing_fields.append("source_hash")
    if suggested_hash is None:
        missing_fields.append("suggested_hash")
    if missing_fields:
        rejection = _record_apply_rejection(runtime, row, "missing_required_fields", missing_fields=missing_fields)
        return None, rejection

    approved_new = _normalized_non_empty_string(row.get("approved_new"))
    if approved_new is None:
        rejection = _record_apply_rejection(runtime, row, "missing_required_fields", missing_fields=["approved_new"])
        return None, rejection
    if approved_new != candidate_value:
        rejection = _record_apply_rejection(
            runtime,
            row,
            "tampered_row_detected",
            expected=candidate_value,
            actual=approved_new,
        )
        return None, rejection

    runtime_value = _normalized_non_empty_string(current_value)
    if runtime_value is None:
        rejection = _record_apply_rejection(runtime, row, "source_hash_mismatch", expected=source_hash, actual="")
        return None, rejection

    actual_source_hash = compute_text_hash(runtime_value)
    if actual_source_hash != source_hash:
        rejection = _record_apply_rejection(
            runtime,
            row,
            "source_hash_mismatch",
            expected=source_hash,
            actual=actual_source_hash,
        )
        return None, rejection

    actual_suggested_hash = compute_text_hash(candidate_value)
    if actual_suggested_hash != suggested_hash:
        rejection = _record_apply_rejection(
            runtime,
            row,
            "suggested_hash_mismatch",
            expected=suggested_hash,
            actual=actual_suggested_hash,
        )
        return None, rejection

    if suggested_hash in applied_suggestions:
        rejection = _record_apply_rejection(runtime, row, "duplicate_application")
        return None, rejection

    return {
        "key": key,
        "locale": locale,
        "current_value": current_row_value,
        "candidate_value": candidate_value,
        "approved_new": approved_new,
        "source_hash": source_hash,
        "suggested_hash": suggested_hash,
        "issue_type": str(row.get("issue_type", "")),
        "plan_id": str(row.get("plan_id", "")),
    }, None


def reconcile_master_from_xlsx(xlsx_path: str, master_path: str) -> None:
    """Sync frozen edits from review_final.xlsx into audit_master.json.

    Matches rows by plan_id only. Never creates new rows — only updates
    existing ones. Missing plan_ids and missing XLSX columns are ignored.
    """
    try:
        rows_data = read_simple_xlsx(Path(xlsx_path))
    except Exception as exc:
        logger.warning("reconcile_master_from_xlsx: failed to read XLSX %s: %s", xlsx_path, exc)
        return

    if not rows_data:
        return

    has_plan_id = any("plan_id" in row for row in rows_data)
    if not has_plan_id:
        logger.warning("reconcile_master_from_xlsx: 'plan_id' column missing in %s — aborting.", xlsx_path)
        return

    has_approved_new = any("approved_new" in row for row in rows_data)
    has_status = any("status" in row for row in rows_data)

    # Build a lookup: plan_id -> {approved_new, status} from XLSX rows
    # Detect duplicates while building the index.
    xlsx_index: dict[str, dict] = {}
    seen_pids: set[str] = set()
    for row in rows_data:
        raw_pid = row.get("plan_id")
        if raw_pid is None or str(raw_pid).strip() == "":
            continue
        pid = str(raw_pid).strip()
        if pid in seen_pids:
            logger.warning("reconcile_master_from_xlsx: duplicate plan_id '%s' in XLSX — last row wins.", pid)
        seen_pids.add(pid)
        entry: dict = {}
        if has_approved_new:
            val = row.get("approved_new")
            entry["approved_new"] = "" if val is None else str(val)
        if has_status:
            val = row.get("status")
            entry["status"] = "" if val is None else str(val)
        xlsx_index[pid] = entry

    if not xlsx_index:
        logger.debug("reconcile_master_from_xlsx: no valid plan_id rows found in XLSX.")
        return

    master_file = Path(master_path)
    if not master_file.exists():
        logger.warning("reconcile_master_from_xlsx: master file not found at %s — aborting.", master_path)
        return

    try:
        master = _json.loads(master_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("reconcile_master_from_xlsx: failed to read master JSON: %s", exc)
        return

    rows = master.get("rows", [])
    if not isinstance(rows, list):
        logger.warning("reconcile_master_from_xlsx: 'rows' key is not a list in master JSON.")
        return

    updated_pids: list[str] = []
    for json_row in rows:
        # Skip non-dict entries defensively
        if not isinstance(json_row, dict):
            logger.debug("reconcile_master_from_xlsx: skipping non-dict row: %r", json_row)
            continue
        raw_pid = json_row.get("plan_id")
        if raw_pid is None or str(raw_pid).strip() == "":
            continue
        pid = str(raw_pid).strip()
        if pid not in xlsx_index:
            continue
        xlsx_entry = xlsx_index[pid]
        if "approved_new" in xlsx_entry:
            json_row["approved_new"] = xlsx_entry["approved_new"]
        if "status" in xlsx_entry:
            json_row["status"] = xlsx_entry["status"]
        updated_pids.append(pid)

    logger.debug("reconcile_master_from_xlsx: updated plan_ids: %s", updated_pids)
    master["rows"] = rows

    # Atomic write: write to .tmp then replace to avoid partial corruption
    tmp_file = master_file.with_suffix(".tmp")
    try:
        tmp_file.write_text(_json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_file.replace(master_file)
        logger.info("reconcile_master_from_xlsx: updated %d rows in %s.", len(updated_pids), master_path)
    except Exception as exc:
        logger.warning("reconcile_master_from_xlsx: failed to write master JSON: %s", exc)
        tmp_file.unlink(missing_ok=True)


def base_ar_mapping(runtime) -> dict[str, object]:
    fixed_candidate = resolve_ar_fixed_json_path(runtime)  # Phase B
    if fixed_candidate.exists():
        return load_locale_mapping(fixed_candidate, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    return load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")


def _stable_identity(row: dict) -> str:
    """Return a stable string identity for a review row.

    Strategy (Phase 3):
    1. Use ``plan_id`` — a UUID generated per-issue at build_review_queue time.
       This is the most stable identity because it is deterministic per audit run
       and is embedded in the XLSX as a non-editable column.
    2. Fallback to a composite key ``key|locale|source_hash`` when plan_id is
       absent or empty, which can happen if the XLSX was hand-crafted or the
       plan_id field was cleared.
    """
    pid = str(row.get("plan_id", "")).strip()
    if pid:
        return pid
    # Composite fallback — still deterministic and unique per distinct issue state
    return "|".join([
        str(row.get("key", "")),
        str(row.get("locale", "")),
        str(row.get("source_hash", "")),
    ])


def reconcile_master(results_dir: Path, all_rows: list[dict], applied_keys: set[str], skipped_keys: dict[str, str]) -> None:
    """Write workflow_state reconciliation into audit_master.json after apply.

    This function is purely additive and safe:
    - If audit_master.json does not exist, it silently returns.
    - On any read/write error it logs a warning and returns without raising.
    - It does NOT mutate issue_inventory, review_projection, or legacy_artifacts.
    - It ONLY writes/overwrites the top-level ``workflow_state`` key.

    Args:
        results_dir: Path to the ``Results/`` directory.
        all_rows: Every row returned by ``read_simple_xlsx`` (complete parse).
        applied_keys: Set of stable identities (from ``_stable_identity``) that
            passed all validation and were committed to the locale files.
        skipped_keys: Dict of stable_identity → skip_reason for rows that were
            rejected during apply validation.
    """
    master_path = results_dir / "artifacts" / "audit_master.json"
    if not master_path.exists():
        logger.debug("Phase 3: audit_master.json not found at %s — skipping reconciliation.", master_path)
        return

    try:
        master = _json.loads(master_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Phase 3: Failed to read audit_master.json: %s", exc)
        return

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    workflow_state: dict[str, dict] = master.get("workflow_state", {})

    for row in all_rows:
        identity = _stable_identity(row)
        if not identity:
            continue

        status_raw = str(row.get("status", "")).strip().lower()
        is_applied = identity in applied_keys
        skip_reason = skipped_keys.get(identity)

        if is_applied:
            resolution = "applied"
        elif skip_reason:
            resolution = "skipped"
        elif status_raw not in ("approved", "auto_safe"):
            resolution = "not_approved"
        else:
            # Approved but not applied and no known skip reason — parse may have failed
            resolution = "parse_failed"

        entry: dict = {
            "key": str(row.get("key", "")),
            "locale": str(row.get("locale", "")),
            "issue_type": str(row.get("issue_type", "")),
            "approved_new": str(row.get("approved_new", "")),
            "status": status_raw,
            "plan_id": str(row.get("plan_id", "")),
            "source_hash": str(row.get("source_hash", "")),
            "suggested_hash": str(row.get("suggested_hash", "")),
            "applied": is_applied,
            "applied_at": now_iso if is_applied else None,
            "resolution_state": resolution,
        }
        if skip_reason:
            entry["skip_reason"] = skip_reason

        workflow_state[identity] = entry

    master["workflow_state"] = workflow_state

    try:
        # Phase A — append a compact entry to apply_history before writing
        now_for_history = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        history_entry = {
            "apply_id": str(uuid.uuid4()),
            "applied_at": now_for_history,
            "source_review_queue": None,   # caller may enrich via future hook
            "rows_selected": len(all_rows),
            "rows_applied": len(applied_keys),
            "rows_skipped": len(skipped_keys),
            "errors": [],
            "fix_plan_reference": None,
        }
        apply_history: list = master.get("apply_history", [])
        if not isinstance(apply_history, list):
            apply_history = []
        apply_history.append(history_entry)
        master["apply_history"] = apply_history

        # Phase A — refresh summaries.workflow applied/not_approved counts
        try:
            summaries = master.get("summaries", {})
            wf = summaries.get("workflow", {}) if isinstance(summaries, dict) else {}
            if isinstance(wf, dict):
                wf["applied_rows"]     = len(applied_keys)
                wf["not_approved_rows"] = sum(
                    1 for e in workflow_state.values()
                    if e.get("resolution_state") == "not_approved"
                )
                summaries["workflow"] = wf
                master["summaries"] = summaries
        except Exception:
            pass  # summaries refresh is best-effort

        master_path.write_text(_json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Phase 3: Reconciled %d entries into audit_master workflow_state.", len(workflow_state))
    except Exception as exc:
        logger.warning("Phase 3: Failed to write reconciled audit_master.json: %s", exc)


def run_apply(runtime, review_queue_path: Path, apply_all: bool = False, out_final_json: str | None = None, out_report: str | None = None) -> dict:
    # Phase 1 — Master Reconciliation: sync frozen workbook edits → audit_master.json BEFORE apply
    if review_queue_path.exists():
        _master_path = resolve_master_path(runtime)
        try:
            reconcile_master_from_xlsx(str(review_queue_path), str(_master_path))
        except Exception as _rec_exc:
            raise RuntimeError(
                f"Master reconciliation failed before apply — aborting to prevent data loss. "
                f"Cause: {_rec_exc}"
            ) from _rec_exc
    else:
        logger.warning("run_apply: review_final workbook does not exist (%s) — skipping pre-apply reconciliation.", review_queue_path)

    # 1. Load auto_fixes from previous run's fix_plan
    auto_fixes_en = {}
    auto_fixes_ar = {}
    plan_path = resolve_fix_plan_path(runtime)  # Phase B
    if plan_path.exists():
        import json as _json
        try:
            plan_data = _json.loads(plan_path.read_text(encoding="utf-8"))
            items = plan_data.get("plan", [])
            for i in items:
                if i.get("classification") == "auto_safe":
                    if i.get("locale") == "en":
                        auto_fixes_en[i["key"]] = i["candidate_value"]
                    else:
                        auto_fixes_ar[i["key"]] = i["candidate_value"]
        except Exception as e:
            logger.warning(f"Could not load previous fix plan: {e}")

    # 2. Load approved fixes from the frozen workbook
    rows = read_simple_xlsx(review_queue_path, required_columns=REQUIRED_REVIEW_COLUMNS)
    # H1 — Artifact type boundary check (must run before any per-row logic).
    _assert_frozen_artifact_type(rows, review_queue_path)
    # H6 — Apply input contract pre-check: verify all required fields are
    # non-empty on every row before any hash comparison or write logic runs.
    _assert_apply_contract(rows, review_queue_path)
    review_fixes_en = {}
    review_fixes_ar = {}
    applied_meta = []
    skipped = []
    apply_trace: list[dict[str, object]] = []
    if hasattr(runtime, "metadata") and isinstance(runtime.metadata, dict):
        runtime.metadata["apply_trace"] = apply_trace
    applied_suggestions_store = _get_applied_suggestions_store(runtime)
    applied_suggestions = set(str(value) for value in applied_suggestions_store if isinstance(value, str))
    
    seen_keys = {} # (key, locale) -> approved_val
    current_en = load_locale_mapping(runtime.en_file, runtime, "en") if runtime.en_file.exists() else {}
    current_ar = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar") if runtime.ar_file.exists() else {}

    # --- Phase 10: Conflict Resolution (Governance Layer) ---
    from l10n_audit.core.conflict_resolution import get_conflict_resolver, MutationRecord
    resolver = get_conflict_resolver(runtime)
    
    # 1. Pre-register auto-fixes from plan (P3) - English only
    for k, v in auto_fixes_en.items():
        resolver.register(MutationRecord(
            key=k,
            original_text=str(current_en.get(k, "")),
            new_text=str(v),
            offset=-1,
            length=0,
            source="auto_fix",
            priority=3
        ))

    for row in rows:
        status = str(row.get("status", "")).strip().lower()
        if not apply_all and status != "approved":
            rejection = _record_apply_rejection(runtime, row, "not_approved_status", actual=status)
            skipped.append(rejection)
            apply_trace.append(
                _build_apply_trace_entry(
                    row,
                    status="skipped",
                    reason="not_approved_status",
                    decision_context={"status": status},
                )
            )
            continue
        
        locale_hint = str(row.get("locale", "")).strip()
        key_hint = str(row.get("key", "")).strip()
        current_val = current_en.get(key_hint) if locale_hint == "en" else current_ar.get(key_hint)
        validated_row, rejection = _validate_apply_row(row, runtime, current_val, applied_suggestions)
        if rejection is not None:
            skipped.append(rejection)
            apply_trace.append(
                _build_apply_trace_entry(
                    row,
                    status="skipped",
                    reason=str(rejection["reason"]),
                    decision_context=_build_rejection_decision_context(
                        row,
                        rejection,
                        current_val,
                        applied_suggestions_store,
                    ),
                )
            )
            continue

        key = validated_row["key"]
        locale = validated_row["locale"]
        approved_val = validated_row["approved_new"]
        suggested_hash = validated_row["suggested_hash"]

        if (key, locale) in seen_keys:
            if seen_keys[(key, locale)] != approved_val:
                rejection = _record_apply_rejection(runtime, row, "conflicting_approved_rows")
                skipped.append(rejection)
                apply_trace.append(
                    _build_apply_trace_entry(
                        row,
                        status="skipped",
                        reason="conflicting_approved_rows",
                        decision_context={},
                    )
                )
                if locale == "en": review_fixes_en.pop(key, None)
                else: review_fixes_ar.pop(key, None)
                continue
        seen_keys[(key, locale)] = approved_val
        
        # --- Phase 10: Governance Enforcement ---
        if locale == "en":
            # Determine if this row came from AI or was purely manual
            row_issue_type = str(row.get("issue_type", "")).lower()
            source_prio = 2 if "ai" in row_issue_type else 1
            source_tag = "ai_review" if source_prio == 2 else "manual"
            
            record = MutationRecord(
                key=key,
                original_text=str(current_val or ""),
                new_text=approved_val,
                offset=-1, # XLSX review rows typically lose granular offsets
                length=0,
                source=source_tag,
                priority=source_prio
            )
            if not resolver.register(record):
                logger.warning("CONFLICT DETECTED: Skipping manual/AI review fix for key '%s' due to priority overlap.", key)
                rejection = _record_apply_rejection(runtime, row, "governance_conflict")
                rejection["source"] = source_tag
                skipped.append(rejection)
                apply_trace.append(
                    _build_apply_trace_entry(
                        row,
                        status="skipped",
                        reason="governance_conflict",
                        decision_context={},
                    )
                )
                continue
            
            review_fixes_en[key] = approved_val
        else:
            review_fixes_ar[key] = approved_val

        applied_suggestions.add(suggested_hash)
        if suggested_hash not in applied_suggestions_store:
            applied_suggestions_store.append(suggested_hash)
            
        applied_meta.append({
            "key": key,
            "locale": locale,
            "new_value": approved_val,
            "issue_type": str(row.get("issue_type", "")),
            # Phase 3: carry plan_id and source_hash so _stable_identity
            # produces the same key as the XLSX row identity.
            "plan_id": str(row.get("plan_id", "")),
            "source_hash": validated_row["source_hash"],
            "suggested_hash": suggested_hash,
        })
        apply_trace.append(
            _build_apply_trace_entry(
                row,
                status="applied",
                reason=None,
                decision_context={
                    "current_value": validated_row["current_value"],
                    "approved_new": validated_row["approved_new"],
                    "source_hash": validated_row["source_hash"],
                    "current_hash": compute_text_hash(validated_row["current_value"]),
                    "suggested_hash": validated_row["suggested_hash"],
                    "validation_passed": True,
                },
            )
        )

    # Update conflict metrics in metadata
    try:
        if hasattr(runtime, "metadata"):
            metrics = resolver.summarize()
            if "conflict_metrics" in runtime.metadata:
                m = runtime.metadata["conflict_metrics"]
                m["conflicts_detected"] += metrics["conflicts_detected"]
                m["conflicts_resolved"] += metrics["conflicts_resolved"]
                m["rejected_low_priority"] += metrics["rejected_low_priority"]
            else:
                runtime.metadata["conflict_metrics"] = metrics
    except Exception:
        pass

    from l10n_audit.fixes.fix_merger import merge_and_export_fixes, merge_mappings
    
    count_en = 0
    final_en = {}
    if runtime.original_en_file:
        final_en = merge_mappings(current_en, auto_fixes_en, review_fixes_en)
        if auto_fixes_en or review_fixes_en:
            merge_and_export_fixes(runtime.original_en_file, auto_fixes_en, review_fixes_en, runtime=runtime)
            count_en = 1
        
    count_ar = 0
    final_ar = {}
    if runtime.original_ar_file:
        final_ar = merge_mappings(current_ar, auto_fixes_ar, review_fixes_ar)
        if auto_fixes_ar or review_fixes_ar:
            merge_and_export_fixes(runtime.original_ar_file, auto_fixes_ar, review_fixes_ar, runtime=runtime)
            count_ar = 1

    if out_final_json:
        out_final_path = Path(out_final_json)
        out_final_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(final_ar if final_ar else final_en, out_final_path)

    report_payload = {
        "summary": {
            "approved_rows_applied": len(applied_meta),
            "approved_rows_skipped": len(skipped),
            "en_fixed_files": count_en,
            "ar_fixed_files": count_ar,
        },
        "applied": [
            {
                "key": item["key"],
                "locale": item["locale"],
                "suggested_hash": item["suggested_hash"],
                "plan_id": item["plan_id"],
            }
            for item in applied_meta
        ],
        "skipped": skipped,
        "trace": apply_trace,
    }

    assert len(apply_trace) == len(applied_meta) + len(skipped)
    assert len(report_payload["applied"]) == report_payload["summary"]["approved_rows_applied"]
    assert len(report_payload["skipped"]) == report_payload["summary"]["approved_rows_skipped"]
    applied_trace_keys = {
        (str(item["plan_id"]), str(item["suggested_hash"]))
        for item in apply_trace
        if item["status"] == "applied"
    }
    for item in report_payload["applied"]:
        assert (str(item["plan_id"]), str(item["suggested_hash"])) in applied_trace_keys

    if out_report:
        out_report_dir = Path(out_report).parent
        out_report_dir.mkdir(parents=True, exist_ok=True)
        write_json(report_payload, Path(out_report))

    # Phase 3 — Post-apply reconciliation into audit_master.json
    # Guarded: any failure here must NOT affect apply behavior.
    try:
        # Build applied_keys set and skipped_keys dict from this run's data.
        applied_set: set[str] = {_stable_identity(m) for m in applied_meta}
        skipped_dict: dict[str, str] = {}
        for s in skipped:
            # Build a proxy row from skipped metadata to compute identity
            proxy = {
                "plan_id": s.get("plan_id", ""),
                "key": s.get("key", ""),
                "locale": s.get("locale", ""),
                "source_hash": s.get("expected_hash", s.get("expected", s.get("source_hash", ""))),
            }
            skipped_dict[_stable_identity(proxy)] = s.get("reason", "unknown")
        reconcile_master(
            results_dir=runtime.results_dir,
            all_rows=rows,
            applied_keys=applied_set,
            skipped_keys=skipped_dict,
        )
    except Exception as reconcile_exc:
        logger.warning("Phase 3: Reconciliation hook raised unexpectedly: %s", reconcile_exc)

    # --- Phase 8: Feedback Signal Capture (observational only) ---
    try:
        from l10n_audit.core.feedback_engine import FeedbackAggregator, FeedbackSignal
        aggregator = FeedbackAggregator()

        for meta in applied_meta:
            aggregator.record(FeedbackSignal(
                route="manual_review",
                confidence=0.5,  # Review-lane fixes don't carry routing confidence
                risk="low",
                was_accepted=True,
                was_modified=False,
                was_rejected=False,
                source="manual",
            ))

        for s in skipped:
            aggregator.record(FeedbackSignal(
                route="manual_review",
                confidence=0.5,
                risk="low",
                was_accepted=False,
                was_modified=False,
                was_rejected=True,
                source="manual",
            ))

        feedback_summary = aggregator.summarize()
        if hasattr(runtime, "metadata"):
            existing = runtime.metadata.get("feedback_metrics", {})
            # Merge: prefer existing signals from autofix stage if present
            if existing:
                combined_total = existing.get("total_signals", 0) + feedback_summary.get("total_signals", 0)
                feedback_summary["total_signals"] = combined_total
            runtime.metadata["feedback_metrics"] = feedback_summary
        logger.debug("Phase 8: Feedback metrics captured — %d signals.", aggregator.signals.__len__())
    except Exception as fb_exc:
        logger.debug("Phase 8: Feedback capture skipped: %s", fb_exc)

    return report_payload


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-queue", default=str(resolve_review_final_path(runtime)))
    parser.add_argument("--out-final-json", default=str(runtime.results_dir / "final_locale" / "ar.final.json"))
    parser.add_argument("--out-report", default=str(runtime.results_dir / "final_locale" / "review_fixes_report.json"))
    parser.add_argument("--all", action="store_true", help="Apply all fixes even if not approved.")
    args = parser.parse_args()

    report = run_apply(
        runtime, 
        Path(args.review_queue), 
        apply_all=args.all, 
        out_final_json=args.out_final_json, 
        out_report=args.out_report
    )
    
    print(f"Applied approved review fixes: {report['summary']['approved_rows_applied']}")
    if report['summary']['en_fixed_files'] > 0 or report['summary']['ar_fixed_files'] > 0:
        print(f"Generated .fix files next to original source(s).")
    print(f"Report:       {args.out_report}")


if __name__ == "__main__":
    main()
