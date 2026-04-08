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

logger = logging.getLogger("l10n_audit.fixes")

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


def _validate_prepare_apply_row(row: Dict[str, Any], row_index: int) -> tuple[Dict[str, str] | None, Dict[str, Any] | None]:
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

    if not normalized["candidate_value"].strip():
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "candidate_value_empty",
            {"status": normalized["status"]},
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

    expected_source_hash = compute_text_hash(normalized["current_value"])
    if expected_source_hash != normalized["source_hash"]:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "source_hash_mismatch",
            {
                "expected_source_hash": expected_source_hash,
                "actual_source_hash": normalized["source_hash"],
            },
        )

    expected_suggested_hash = compute_text_hash(normalized["candidate_value"])
    if expected_suggested_hash != normalized["suggested_hash"]:
        return None, _prepare_apply_rejection(
            row_index,
            row,
            "suggested_hash_mismatch",
            {
                "expected_suggested_hash": expected_suggested_hash,
                "actual_suggested_hash": normalized["suggested_hash"],
            },
        )

    return {
        "key": normalized["key"],
        "locale": normalized["locale"],
        "issue_type": normalized["issue_type"],
        "current_value": normalized["current_value"],
        "candidate_value": normalized["candidate_value"],
        "approved_new": normalized["candidate_value"],
        "status": "approved",
        "review_note": normalized["review_note"],
        "source_old_value": normalized["source_old_value"],
        "source_hash": expected_source_hash,
        "suggested_hash": expected_suggested_hash,
        "plan_id": normalized["plan_id"],
        "generated_at": normalized["generated_at"],
    }, None


def prepare_apply_workbook(
    review_queue_path: Path,
    out_final_path: Path,
    rejection_report_path: Path,
) -> Dict[str, Any]:
    out_final_path.parent.mkdir(parents=True, exist_ok=True)
    rejection_report_path.parent.mkdir(parents=True, exist_ok=True)

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

    for idx, row in enumerate(rows, start=2):
        if not isinstance(row, dict):
            rejections.append(
                _prepare_apply_rejection(
                    idx,
                    {},
                    "invalid_row_shape",
                    {"python_type": type(row).__name__},
                )
            )
            continue

        accepted_row, rejection = _validate_prepare_apply_row(row, idx)
        if rejection is not None:
            rejections.append(rejection)
            continue
        accepted_rows.append(accepted_row)

    write_simple_xlsx(accepted_rows, REVIEW_FINAL_COLUMNS, out_final_path, sheet_name="Review Final")

    report = {
        "summary": {
            "total_rows": len(rows),
            "accepted_rows": len(accepted_rows),
            "rejected_rows": len(rejections),
        },
        "rejections": rejections,
    }
    write_json(report, rejection_report_path)
    return report
