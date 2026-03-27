#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from pathlib import Path

from l10n_audit.core.audit_runtime import AuditRuntimeError, compute_text_hash, load_locale_mapping, load_runtime, read_simple_xlsx, write_json

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


def base_ar_mapping(runtime) -> dict[str, object]:
    fixed_candidate = runtime.results_dir / "fixes" / "ar.fixed.json"
    if fixed_candidate.exists():
        return load_locale_mapping(fixed_candidate, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    return load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")


def run_apply(runtime, review_queue_path: Path, apply_all: bool = False, out_final_json: str | None = None, out_report: str | None = None) -> dict:
    # 1. Load auto_fixes from previous run's fix_plan
    auto_fixes_en = {}
    auto_fixes_ar = {}
    plan_path = runtime.results_dir / "fixes" / "fix_plan.json"
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
        
        if locale == "en":
            review_fixes_en[key] = approved_val
        else:
            review_fixes_ar[key] = approved_val
            
        applied_meta.append({
            "key": key,
            "locale": locale,
            "new_value": approved_val,
            "issue_type": str(row.get("issue_type", ""))
        })

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
