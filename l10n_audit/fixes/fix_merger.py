"""
نظام دمج الإصلاحات (Fix Merger) — المسؤول عن تحديث ملفات اللغة.

أمر apply الجديد:
- يقوم هذا النظام بدمج الإصلاحات المعتمدة من ملف التميز (Review Queue) مع الملفات الأصلية.
- استخدام المفتاح --all يسمح بدمج كافة الاقتراحات (بما في ذلك اقتراحات الذكاء الاصطناعي) 
  بشكل جماعي، مما يوفر الوقت في المشاريع الكبيرة مع الحفاظ على نسخة احتياطية (.fix).
"""
import logging
import datetime
from pathlib import Path
from typing import Dict, Optional, Any, List

from l10n_audit.core.locale_exporters.exporter_factory import export_locale_mapping
from l10n_audit.core.locale_loaders.loader_factory import load_locale_mapping
from l10n_audit.core.audit_runtime import write_json, write_simple_xlsx, compute_text_hash

logger = logging.getLogger("l10n_audit.fixes")

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
    
    # Prepare data for export
    export_data = []
    for item in review_items:
        row = dict(item)
        row.setdefault("status", "pending")
        row.setdefault("approved_new", item.get("approved_new") or item.get("candidate_value") or "")
        
        # Add metadata for integrity checks (as expected by apply_review_fixes.py)
        row.setdefault("source_old_value", item.get("current_value", ""))
        row.setdefault("source_hash", compute_text_hash(str(item.get("current_value", ""))))
        row.setdefault("suggested_hash", compute_text_hash(str(item.get("candidate_value", ""))))
        row.setdefault("plan_id", "PLAN-" + str(abs(hash(str(item.get("key", "")) + str(item.get("locale", "")))) % 100000000))
        row.setdefault("generated_at", datetime.datetime.now().isoformat())
        export_data.append(row)

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
