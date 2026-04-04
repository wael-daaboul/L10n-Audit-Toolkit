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
from l10n_audit.core.artifact_resolver import resolve_ar_fixed_json_path, resolve_fix_plan_path, resolve_master_path

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


def reconcile_master_from_xlsx(xlsx_path: str, master_path: str) -> None:
    """Sync human edits from review_queue.xlsx into audit_master.json.

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
    # Phase 1 — Master Reconciliation: sync XLSX human edits → audit_master.json BEFORE apply
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
        logger.warning("run_apply: review_queue_path does not exist (%s) — skipping pre-apply reconciliation.", review_queue_path)

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

    # 2. Load approved fixes from Excel
    rows = read_simple_xlsx(review_queue_path, required_columns=REQUIRED_REVIEW_COLUMNS)
    review_fixes_en = {}
    review_fixes_ar = {}
    applied_meta = []
    skipped = []
    
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
            continue
            
        key = str(row.get("key", "")).strip()
        locale = str(row.get("locale", "")).strip()
        approved_val = str(row.get("approved_new", ""))
        
        # If apply_all is on but approved_new is empty, use suggested_fix instead
        if apply_all and not approved_val:
            approved_val = str(row.get("suggested_fix", ""))

        if not approved_val:
            continue

        if not key:
            skipped.append({"key": key, "reason": "empty_key"})
            continue
            
        if (key, locale) in seen_keys:
            if seen_keys[(key, locale)] != approved_val:
                skipped.append({"key": key, "locale": locale, "reason": "conflicting_approved_rows"})
                if locale == "en": review_fixes_en.pop(key, None)
                else: review_fixes_ar.pop(key, None)
                continue
        seen_keys[(key, locale)] = approved_val

        source_hash = str(row.get("source_hash", ""))
        current_val = current_en.get(key) if locale == "en" else current_ar.get(key)
        if current_val is not None:
            current_hash = compute_text_hash(str(current_val))
            if current_hash != source_hash:
                skipped.append({"key": key, "locale": locale, "reason": "stale_source", "expected_hash": source_hash, "actual_hash": current_hash})
                continue

        suggested_hash = str(row.get("suggested_hash", "")).strip()
        if suggested_hash:
            actual_suggested_hash = compute_text_hash(approved_val)
            if actual_suggested_hash != suggested_hash:
                skipped.append({"key": key, "locale": locale, "reason": "suggested_hash_mismatch", "expected": suggested_hash, "actual": actual_suggested_hash})
                continue
        
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
                skipped.append({"key": key, "locale": locale, "reason": "governance_conflict", "source": source_tag})
                continue
            
            review_fixes_en[key] = approved_val
        else:
            review_fixes_ar[key] = approved_val
            
        applied_meta.append({
            "key": key,
            "locale": locale,
            "new_value": approved_val,
            "issue_type": str(row.get("issue_type", "")),
            # Phase 3: carry plan_id and source_hash so _stable_identity
            # produces the same key as the XLSX row identity.
            "plan_id": str(row.get("plan_id", "")),
            "source_hash": str(row.get("source_hash", "")),
        })

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
        "applied": applied_meta,
        "skipped": skipped,
    }

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
                "source_hash": s.get("expected_hash", s.get("source_hash", "")),
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
    parser.add_argument("--review-queue", default=str(runtime.results_dir / "review" / "review_queue.xlsx"))
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
