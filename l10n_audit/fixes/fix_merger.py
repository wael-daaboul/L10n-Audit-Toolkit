"""
نظام دمج الإصلاحات (Fix Merger) — المسؤول عن تحديث ملفات اللغة.

أمر apply الجديد:
- يقوم هذا النظام بدمج الإصلاحات المعتمدة من ملف التميز (Review Queue) مع الملفات الأصلية.
- استخدام المفتاح --all يسمح بدمج كافة الاقتراحات (بما في ذلك اقتراحات الذكاء الاصطناعي) 
  بشكل جماعي، مما يوفر الوقت في المشاريع الكبيرة مع الحفاظ على نسخة احتياطية (.fix).
"""
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List

from l10n_audit.core.locale_exporters.exporter_factory import export_locale_mapping
from l10n_audit.core.locale_loaders.loader_factory import load_locale_mapping
from l10n_audit.core.audit_runtime import read_simple_xlsx, write_json, write_simple_xlsx, compute_text_hash
from l10n_audit.core.hydration_result import UNRESOLVED_LOOKUP_SOURCE_HASH
from l10n_audit.core.source_identity import canonical_source_guard_enabled, compute_canonical_source_hash
from l10n_audit.core.source_hash_diagnostics import emit_source_hash_compare

logger = logging.getLogger("l10n_audit.fixes")

# ---------------------------------------------------------------------------
# H1 Artifact type marker
# ---------------------------------------------------------------------------
FROZEN_ARTIFACT_TYPE_VALUE: str = "frozen_apply_artifact"

# ---------------------------------------------------------------------------
# H3 Plan-id cross-check
# ---------------------------------------------------------------------------
STALE_PLAN_ID_REASON_CODE: str = "stale_plan_id"

# ---------------------------------------------------------------------------
# H2 Promotion report outcomes
# ---------------------------------------------------------------------------
PROMOTION_OUTCOME_PROMOTED: str = "promoted"
PROMOTION_OUTCOME_REJECTED: str = "rejected"

# ---------------------------------------------------------------------------
# H4 Integrity drift detection
# ---------------------------------------------------------------------------
# Reason codes used in rejection records when a workbook row’s immutable field
# differs from the machine-generated source.
INTEGRITY_DRIFT_REASON_CODE: str = "integrity_drift"
MACHINE_SOURCE_NOT_FOUND_REASON_CODE: str = "machine_source_row_not_found"
MACHINE_ARTIFACT_UNREADABLE_REASON_CODE: str = "machine_artifact_unreadable"

# Fields that are written by the pipeline and must NOT be edited by a reviewer.
# Drift in any of these fields is treated as tampering and causes promotion
# rejection.  Human-editable fields (approved_new, status, review_note) are
# deliberately excluded from this set.
H4_IMMUTABLE_FIELDS: tuple[str, ...] = (
    "key",
    "locale",
    "plan_id",
    "source_hash",
    "suggested_hash",
    "generated_at",
    "issue_type",
    "source_old_value",
)

# ---------------------------------------------------------------------------
# H5 Override Acknowledgement
# ---------------------------------------------------------------------------
# Reason code written into the rejection record when a reviewer has changed
# approved_new to a value different from candidate_value but has not set
# override_acknowledged = "true" to explicitly acknowledge the choice.
OVERRIDE_NOT_ACK_REASON_CODE: str = "override_not_acknowledged"

REVIEW_FINAL_COLUMNS = [
    "key",
    "locale",
    "issue_type",
    "current_value",
    "candidate_value",
    "approved_new",
    "status",
    "review_note",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
    "frozen_artifact_type",
]

_REQUIRED_PREPARE_QUEUE_FIELDS = (
    "key",
    "locale",
    "issue_type",
    "current_value",
    "candidate_value",
    "status",
    "review_note",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
)


def _normalized_non_empty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value.strip() else None


def _record_review_export_rejection(
    runtime: Any,
    item: Dict[str, Any],
    missing_fields: List[str],
) -> None:
    rejection = {
        "key": str(item.get("key", "")),
        "source": str(item.get("source", "")),
        "issue_type": str(item.get("issue_type", "")),
        "missing_fields": missing_fields,
        "reason": "incomplete_review_export_contract",
    }
    if runtime is not None and hasattr(runtime, "metadata") and isinstance(runtime.metadata, dict):
        runtime.metadata.setdefault("review_export_rejections", []).append(rejection)
        invalid_entry = {
            "key": str(item.get("key", "")),
            "plan_id": str(item.get("plan_id", "")),
            "missing_fields": list(missing_fields),
            "raw_item_snapshot": dict(item),
        }
        runtime.metadata.setdefault("invalid_review_rows", []).append(invalid_entry)
        counter = runtime.metadata.setdefault("invalid_review_rows_reasons_breakdown", {})
        if isinstance(counter, dict):
            for field in missing_fields:
                breakdown_key = f"missing_{field}"
                counter[breakdown_key] = int(counter.get(breakdown_key, 0)) + 1
        runtime.metadata["invalid_review_rows_count"] = len(runtime.metadata.get("invalid_review_rows", []))
        return
    logger.debug("Dropping review export item: %s", rejection)


def validate_review_row(item: Dict[str, Any]) -> tuple[bool, List[str]]:
    key = _normalized_non_empty_string(item.get("key"))
    locale = _normalized_non_empty_string(item.get("locale"))
    issue_type = _normalized_non_empty_string(item.get("issue_type"))
    message = _normalized_non_empty_string(item.get("message"))
    current_value = _normalized_non_empty_string(item.get("current_value"))
    candidate_value = _normalized_non_empty_string(item.get("candidate_value"))
    generated_at = _normalized_non_empty_string(item.get("generated_at"))
    approved_new = candidate_value

    missing_fields: List[str] = []
    if key is None:
        missing_fields.append("key")
    if locale not in {"ar", "en"}:
        missing_fields.append("locale")
    if issue_type is None:
        missing_fields.append("issue_type")
    if message is None:
        missing_fields.append("message")
    if current_value is None:
        missing_fields.append("current_value")
    if candidate_value is None:
        missing_fields.append("candidate_value")
    if candidate_value is not None and approved_new is None:
        missing_fields.append("approved_new")
    if generated_at is None:
        missing_fields.append("generated_at")
    return len(missing_fields) == 0, missing_fields


def build_validated_row(item: Dict[str, Any], runtime: Any) -> Dict[str, Any] | None:
    is_valid, missing_fields = validate_review_row(item)
    if not is_valid:
        _record_review_export_rejection(runtime, item, missing_fields)
        return None

    key = _normalized_non_empty_string(item.get("key"))
    locale = _normalized_non_empty_string(item.get("locale"))
    issue_type = _normalized_non_empty_string(item.get("issue_type"))
    message = _normalized_non_empty_string(item.get("message"))
    current_value = _normalized_non_empty_string(item.get("current_value"))
    candidate_value = _normalized_non_empty_string(item.get("candidate_value"))
    approved_new = candidate_value
    source_old_value = current_value
    status = str(item.get("status", "")).strip() or "pending"
    plan_id = str(item.get("plan_id", "")).strip() or f"PLAN-{compute_text_hash(f'{key}|{locale}')[:12]}"
    generated_at = _normalized_non_empty_string(item.get("generated_at"))

    return {
        "key": key,
        "locale": locale,
        "issue_type": issue_type,
        "message": message,
        "current_value": current_value,
        "candidate_value": candidate_value,
        "approved_new": approved_new,
        "status": status,
        "source_old_value": source_old_value,
        "source_hash": compute_text_hash(current_value),
        "suggested_hash": compute_text_hash(candidate_value),
        "plan_id": plan_id,
        "generated_at": generated_at,
    }

def merge_mappings(base: Dict[str, Any], auto: Dict[str, str], review: Dict[str, str]) -> Dict[str, Any]:
    """
    Merge base, auto, and review mappings (review overrides auto, auto overrides base).
    """
    final = dict(base)
    # 1. Apply auto fixes
    for k, v in auto.items():
        if k in final:
            final[k] = v
            
    # 2. Apply review fixes (overrides)
    for k, v in review.items():
        if k in final:
            final[k] = v
    return final

def merge_and_export_fixes(
    original_path: Path,
    auto_fixes: Dict[str, str],
    review_fixes: Optional[Dict[str, str]] = None,
    runtime: Any = None,
    output_suffix: str = ".fix"
) -> List[Path]:
    """
    Merge auto and reviewed fixes, then export as .fix file(s) next to original.
    Returns list of paths created.
    """
    if runtime is None:
        logger.error("Audit runtime is required for merging and exporting fixes.")
        return []

    # 1. Load original data
    try:
        # Load from the isolated workspace copy to ensure we have the same structure we audited
        data = load_locale_mapping(original_path, runtime.locale_format)
    except Exception as e:
        logger.error(f"Failed to load original data from {original_path}: {e}")
        return []

    # 2. Merge fixes (review overrides auto)
    merged_fixes = auto_fixes.copy()
    if review_fixes:
        merged_fixes.update(review_fixes)

    # 3. Apply fixes
    updated_data = dict(data)
    applied_count = 0
    for key, new_val in merged_fixes.items():
        if key in updated_data:
            if updated_data[key] != new_val:
                updated_data[key] = new_val
                applied_count += 1

    # 4. Determine output path next to the ORIGINAL file (not in workspace)
    # Note: original_path might be pointing to workspace/en.json
    # We want to find the true original path.
    # runtime.project_root comparison? Or assume the user wants it next to their source.
    # Actually, the user's prompt says "بجانب الملفات الأصلية".
    # We should probably get the true source path from runtime if we are in run mode.
    
    # If original_path is already in workspace, find its corresponding source path
    # But for simplicity, we can let the caller pass the desired original path.
    # Let's assume original_path is the one we want to stay "next to".
    
    # Check if original_path is file or directory
    if original_path.is_file():
        # e.g. en.json -> en.fix.json
        output_path = original_path.parent / (original_path.stem + output_suffix + original_path.suffix)
    else:
        # e.g. resources/lang/en -> resources/lang/en.fix
        output_path = original_path.parent / (original_path.name + output_suffix)

    # 5. Export
    try:
        exported_paths = export_locale_mapping(updated_data, runtime.locale_format, output_path)
        logger.info(f"Exported {len(exported_paths)} fixed files to {output_path} (Modified {applied_count} keys)")
        return exported_paths
    except Exception as e:
        logger.error(f"Failed to export fixed data to {output_path}: {e}")
        return []

def export_review_queue(
    fix_plan: List[Dict[str, Any]], 
    runtime: Any, 
    output_path: Path
) -> Path:
    """
    Export fixes requiring review to an Excel or JSON file.
    Includes technical metadata for apply_review_fixes.py integrity checks.
    """
    review_items = [item for item in fix_plan if item.get("classification") == "review_required"]
    if not review_items:
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if runtime is not None and hasattr(runtime, "metadata") and isinstance(runtime.metadata, dict):
        runtime.metadata.setdefault("invalid_review_rows", [])
        runtime.metadata.setdefault("invalid_review_rows_reasons_breakdown", {})
        runtime.metadata.setdefault("invalid_review_rows_count", 0)
    
    # Prepare data for export
    export_data = []
    for item in review_items:
        row = build_validated_row(item, runtime)
        if row is not None:
            export_data.append(row)

    if not export_data:
        logger.info("No valid review_required items were exportable for review queue: %s", output_path)
        return output_path

    # Required columns for apply_review_fixes.py
    columns = [
        "key", "locale", "issue_type", "message", 
        "current_value", "candidate_value", "approved_new", "status",
        "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at"
    ]

    if output_path.suffix == ".xlsx":
        write_simple_xlsx(export_data, columns, output_path, sheet_name="Review Queue")
    else:
        write_json({"review_queue": export_data}, output_path)
    
    logger.info(f"Exported {len(export_data)} items to review queue: {output_path}")
    return output_path


def _load_machine_queue_index(
    machine_queue_path: Path,
) -> Dict[tuple, Dict[str, Any]] | None:
    """
    H4 — Load the machine queue JSON and return an index keyed by
    (key, locale, plan_id) for O(1) lookup during promotion.

    Returns
    -------
    dict[(key, locale, plan_id) -> row_dict]
        When the file is loaded and the expected structure is present.
    None
        When the file is missing (so callers can distinguish
        “not provided” from “unreadable”; missing is handled before calling).

    Raises
    ------
    ValueError
        When the file exists but cannot be parsed or has an unexpected structure.
        Callers convert this into a machine_artifact_unreadable rejection.
    """
    import json as _json
    try:
        raw = _json.loads(machine_queue_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Cannot read machine queue at '{machine_queue_path}': {exc}") from exc

    rows = raw.get("review_queue")
    if not isinstance(rows, list):
        raise ValueError(
            f"Machine queue at '{machine_queue_path}' has unexpected structure: "
            f"'review_queue' key missing or not a list."
        )

    index: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "") or "")
        locale = str(row.get("locale", "") or "")
        plan_id = str(row.get("plan_id", "") or "")
        identity = (key, locale, plan_id)
        index[identity] = row
    return index


def _check_integrity_drift(
    workbook_row: Dict[str, Any],
    machine_row: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    H4 — Compare a workbook row against its machine-queue counterpart.

    Returns a list of drift records, one per drifted field::

        [{"field": "source_hash",
          "machine_value": "abc",
          "workbook_value": "xyz"}, ...]

    An empty list means no drift was detected.
    Only fields in H4_IMMUTABLE_FIELDS are compared.
    """
    drifted: List[Dict[str, str]] = []
    for field in H4_IMMUTABLE_FIELDS:
        machine_val = str(machine_row.get(field, "") or "")
        workbook_val = str(workbook_row.get(field, "") or "")
        if machine_val != workbook_val:
            drifted.append({
                "field": field,
                "machine_value": machine_val,
                "workbook_value": workbook_val,
            })
    return drifted


def _prepare_apply_rejection(
    row_index: int,
    row: Dict[str, Any],
    reason_code: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "row_index": row_index,
        "plan_id": str(row.get("plan_id", "") or ""),
        "key": str(row.get("key", "") or ""),
        "locale": str(row.get("locale", "") or ""),
        "reason_code": reason_code,
        "details": details,
    }


def _promotion_record(
    row_index: int,
    row: Dict[str, Any],
    outcome: str,
    reason_code: str,
) -> Dict[str, Any]:
    """H2 — Build a single per-row entry for the promotion report 'rows' list.

    Every input row (promoted OR rejected) gets one entry so the report is a
    complete, ordered account of all promotion decisions.

    Fields
    ------
    row_index   : 1-based row number in the source workbook (2 = first data row)
    key         : finding identity
    locale      : locale identity
    plan_id     : pipeline run identity (empty string when absent)
    outcome     : PROMOTION_OUTCOME_PROMOTED or PROMOTION_OUTCOME_REJECTED
    reason_code : why promoted ('all_checks_passed') or why rejected
    """
    return {
        "row_index": row_index,
        "key": str(row.get("key", "") or ""),
        "locale": str(row.get("locale", "") or ""),
        "plan_id": str(row.get("plan_id", "") or ""),
        "outcome": outcome,
        "reason_code": reason_code,
    }


def _validate_prepare_apply_row(
    row: Dict[str, Any],
    row_index: int,
    *,
    allowed_plan_ids: frozenset[str] | None = None,
    machine_index: Dict[tuple, Dict[str, Any]] | None = None,
    diagnostics_results_dir: Path | None = None,
) -> tuple[Dict[str, str] | None, Dict[str, Any] | None]:
    """
    Validate a single row for promotion into review_final.xlsx.

    Parameters
    ----------
    row
        The raw dict row from read_simple_xlsx.
    row_index
        1-based row index in the source workbook (used in rejection records).
    allowed_plan_ids
        H3 — When provided, the row’s plan_id must be in this set or the
        row is rejected with reason_code STALE_PLAN_ID_REASON_CODE.
        When None, no plan cross-check is performed (backward-compatible
        default for callers that do not know the valid plan set).
    machine_index
        H4 — When provided, the row’s immutable fields are compared against
        the machine-queue source row identified by (key, locale, plan_id).
        Rows with any drift are rejected with INTEGRITY_DRIFT_REASON_CODE.
        Rows with no matching machine source are rejected with
        MACHINE_SOURCE_NOT_FOUND_REASON_CODE.
        When None, no drift check is performed (backward-compatible default).
    """
    normalized = {field: "" if row.get(field) is None else str(row.get(field)) for field in _REQUIRED_PREPARE_QUEUE_FIELDS}

    for field in (
        "key",
        "locale",
        "issue_type",
        "current_value",
        "plan_id",
        "generated_at",
        "source_old_value",
        "source_hash",
        "suggested_hash",
    ):
        if not normalized[field].strip():
            return None, _prepare_apply_rejection(
                row_index,
                row,
                "missing_required_field",
                {"field": field},
            )

    # H3 — plan_id cross-check: reject rows whose plan_id is not in the
    # caller-supplied allowed set.  Runs after the empty-string check above
    # so that missing_required_field is reported first for empty plan_ids.
    if allowed_plan_ids is not None:
        row_plan_id = normalized["plan_id"].strip()
        if row_plan_id not in allowed_plan_ids:
            return None, _prepare_apply_rejection(
                row_index,
                row,
                STALE_PLAN_ID_REASON_CODE,
                {
                    "row_plan_id": row_plan_id,
                    "allowed_plan_ids": sorted(allowed_plan_ids),
                },
            )

    # H4 — Integrity drift check: compare immutable fields against the machine
    # source.  Runs after H3 so stale-plan rows are caught before touching the
    # machine index (plan_id must be valid for the index lookup to be meaningful).
    if machine_index is not None:
        identity = (
            normalized["key"].strip(),
            normalized["locale"].strip(),
            normalized["plan_id"].strip(),
        )
        machine_row = machine_index.get(identity)
        if machine_row is None:
            return None, _prepare_apply_rejection(
                row_index,
                row,
                MACHINE_SOURCE_NOT_FOUND_REASON_CODE,
                {
                    "identity": list(identity),
                    "note": (
                        "No matching machine-queue row found for this "
                        "(key, locale, plan_id) combination."
                    ),
                },
            )
        drifted = _check_integrity_drift(row, machine_row)
        if drifted:
            return None, _prepare_apply_rejection(
                row_index,
                row,
                INTEGRITY_DRIFT_REASON_CODE,
                {
                    "drifted_fields": drifted,
                    "note": (
                        "One or more immutable fields were modified after "
                        "machine emission. Only approved_new, status, and "
                        "review_note are human-editable."
                    ),
                },
            )

    if normalized["locale"].strip() not in {"ar", "en"}:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "invalid_locale",
            {"locale": normalized["locale"]},
        )

    if normalized["status"].strip().lower() != "approved":
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "invalid_status_for_freeze",
            {"status": normalized["status"]},
        )

    candidate_val = normalized["candidate_value"].strip()
    approved_new_raw = str(row.get("approved_new", "") or "").strip()

    if not candidate_val and not approved_new_raw:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "missing_final_text",
            {"status": normalized["status"]},
        )

    if candidate_val and approved_new_raw and candidate_val != approved_new_raw:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "divergent_human_edits",
            {
                "candidate_value": candidate_val,
                "approved_new": approved_new_raw,
            },
        )

    if normalized["source_old_value"] != normalized["current_value"]:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "source_value_mismatch",
            {
                "current_value": normalized["current_value"],
                "source_old_value": normalized["source_old_value"],
            },
        )

    canonical_guard_on = canonical_source_guard_enabled()
    source_guard_mode = "canonical" if canonical_guard_on else "raw"
    expected_source_hash = compute_text_hash(normalized["current_value"])
    canonical_expected_source_hash = compute_canonical_source_hash(normalized["source_old_value"])
    canonical_actual_source_hash = compute_canonical_source_hash(normalized["current_value"])
    raw_hash_match = expected_source_hash == normalized["source_hash"]
    canonical_hash_match = canonical_actual_source_hash == canonical_expected_source_hash
    authoritative_hash_match = canonical_hash_match if canonical_guard_on else raw_hash_match
    emit_source_hash_compare(
        phase="prepare_apply",
        carrier="workbook.current_value",
        key=normalized["key"],
        locale=normalized["locale"],
        plan_id=normalized["plan_id"],
        row_index=row_index,
        value=normalized["current_value"],
        stored_source_hash=normalized["source_hash"],
        actual_source_hash=expected_source_hash,
        canonical_stored_source_hash=canonical_expected_source_hash,
        canonical_actual_source_hash=canonical_actual_source_hash,
        canonical_hash_match=canonical_hash_match,
        source_guard_mode=source_guard_mode,
        authoritative_hash_kind=source_guard_mode,
        authoritative_hash_match=authoritative_hash_match,
        results_dir=diagnostics_results_dir,
    )
    if normalized["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "source_hash_mismatch",
            {
                "expected_source_hash": expected_source_hash,
                "actual_source_hash": normalized["source_hash"],
                "source_guard_mode": source_guard_mode,
                "canonical_expected_source_hash": canonical_expected_source_hash,
                "canonical_actual_source_hash": canonical_actual_source_hash,
            },
        )

    if not authoritative_hash_match:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "source_hash_mismatch",
            {
                "expected_source_hash": expected_source_hash,
                "actual_source_hash": normalized["source_hash"],
                "source_guard_mode": source_guard_mode,
                "canonical_expected_source_hash": canonical_expected_source_hash,
                "canonical_actual_source_hash": canonical_actual_source_hash,
            },
        )

    final_approved_text = approved_new_raw if approved_new_raw else candidate_val
    frozen_source_hash = normalized["source_hash"] if canonical_guard_on else expected_source_hash

    return {
        "key": normalized["key"],
        "locale": normalized["locale"],
        "issue_type": normalized["issue_type"],
        "current_value": normalized["current_value"],
        "candidate_value": normalized["candidate_value"],
        "approved_new": final_approved_text,
        "status": "approved",
        "review_note": normalized["review_note"],
        "source_old_value": normalized["source_old_value"],
        "source_hash": frozen_source_hash,
        "suggested_hash": normalized["suggested_hash"],
        "plan_id": normalized["plan_id"],
        "generated_at": normalized["generated_at"],
        "frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE,
    }, None


def prepare_apply_workbook(
    review_queue_path: Path,
    out_final_path: Path,
    rejection_report_path: Path,
    *,
    allowed_plan_ids: frozenset[str] | None = None,
    machine_queue_path: Path | None = None,
) -> Dict[str, Any]:
    """
    Promote eligible rows from review_queue_path into review_final.xlsx.

    Parameters
    ----------
    review_queue_path
        Path to the human-edited review workbook.
    out_final_path
        Path where the frozen apply artifact will be written.
    rejection_report_path
        Path where the rejection report JSON will be written.
    allowed_plan_ids
        H3 — When provided, only rows whose plan_id is in this set will be
        promoted.  Rows with a plan_id outside this set receive a
        STALE_PLAN_ID_REASON_CODE rejection.
        When None (default), no plan cross-check is performed.
    machine_queue_path
        H4 — When provided, each workbook row’s immutable fields are compared
        against the pipeline-generated machine queue JSON at this path.
        If the file is missing, all rows are rejected with
        MACHINE_ARTIFACT_UNREADABLE_REASON_CODE (fail-loudly semantic).
        If the file is malformed, all rows are rejected the same way.
        If a workbook row has no matching machine-source row, it is rejected
        with MACHINE_SOURCE_NOT_FOUND_REASON_CODE.
        When None (default), no drift check is performed; all existing
        callers that omit this argument continue to behave identically.
    """
    out_final_path.parent.mkdir(parents=True, exist_ok=True)
    rejection_report_path.parent.mkdir(parents=True, exist_ok=True)

    # H4 — Pre-load machine index when drift detection is requested.
    # A missing or malformed machine artifact causes all rows to be rejected;
    # there is no silent fallback.
    machine_index: Dict[tuple, Dict[str, Any]] | None = None
    if machine_queue_path is not None:
        if not machine_queue_path.exists():
            write_simple_xlsx([], REVIEW_FINAL_COLUMNS, out_final_path, sheet_name="Review Final")
            all_rows_rejected = _prepare_apply_rejection(
                0, {},
                MACHINE_ARTIFACT_UNREADABLE_REASON_CODE,
                {"error": f"Machine queue file not found: '{machine_queue_path}'"},
            )
            report = {
                "summary": {"total_rows": 0, "accepted_rows": 0, "rejected_rows": 1},
                "rows": [],
                "rejections": [all_rows_rejected],
            }
            write_json(report, rejection_report_path)
            return report
        try:
            machine_index = _load_machine_queue_index(machine_queue_path)
        except ValueError as exc:
            write_simple_xlsx([], REVIEW_FINAL_COLUMNS, out_final_path, sheet_name="Review Final")
            all_rows_rejected = _prepare_apply_rejection(
                0, {},
                MACHINE_ARTIFACT_UNREADABLE_REASON_CODE,
                {"error": str(exc)},
            )
            report = {
                "summary": {"total_rows": 0, "accepted_rows": 0, "rejected_rows": 1},
                "rows": [],
                "rejections": [all_rows_rejected],
            }
            write_json(report, rejection_report_path)
            return report

    try:
        rows = read_simple_xlsx(review_queue_path, required_columns=list(_REQUIRED_PREPARE_QUEUE_FIELDS))
    except Exception as exc:
        write_simple_xlsx([], REVIEW_FINAL_COLUMNS, out_final_path, sheet_name="Review Final")
        report = {
            "summary": {
                "total_rows": 0,
                "accepted_rows": 0,
                "rejected_rows": 1,
            },
            "rows": [],                # H2 — no per-row data when input was unreadable
            "rejections": [
                _prepare_apply_rejection(
                    0,
                    {},
                    "invalid_row_shape",
                    {"error": str(exc)},
                )
            ],
        }
        write_json(report, rejection_report_path)
        return report

    accepted_rows: List[Dict[str, str]] = []
    rejections: List[Dict[str, Any]] = []
    promotion_rows: List[Dict[str, Any]] = []  # H2 — per-row outcome list

    for idx, row in enumerate(rows, start=2):
        if not isinstance(row, dict):
            rejection = _prepare_apply_rejection(
                idx,
                {},
                "invalid_row_shape",
                {"python_type": type(row).__name__},
            )
            rejections.append(rejection)
            promotion_rows.append(
                _promotion_record(idx, {}, PROMOTION_OUTCOME_REJECTED, "invalid_row_shape")
            )
            continue

        accepted_row, rejection = _validate_prepare_apply_row(
            row, idx,
            allowed_plan_ids=allowed_plan_ids,
            machine_index=machine_index,
            diagnostics_results_dir=out_final_path.parent.parent,
        )
        if rejection is not None:
            rejections.append(rejection)
            promotion_rows.append(
                _promotion_record(
                    idx, row, PROMOTION_OUTCOME_REJECTED, rejection["reason_code"]
                )
            )
            continue
        accepted_rows.append(accepted_row)
        promotion_rows.append(
            _promotion_record(idx, row, PROMOTION_OUTCOME_PROMOTED, "all_checks_passed")
        )

    write_simple_xlsx(accepted_rows, REVIEW_FINAL_COLUMNS, out_final_path, sheet_name="Review Final")

    report = {
        "summary": {
            "total_rows": len(rows),
            "accepted_rows": len(accepted_rows),
            "rejected_rows": len(rejections),
        },
        "rows": promotion_rows,        # H2 — per-row outcome list (promoted + rejected)
        "rejections": rejections,      # backward-compatible rejection-only list
    }
    write_json(report, rejection_report_path)
    return report
