#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from core.audit_runtime import AuditRuntimeError, compute_text_hash, load_locale_mapping, load_runtime, read_simple_xlsx, write_json

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


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-queue", default=str(runtime.results_dir / "review" / "review_queue.xlsx"))
    parser.add_argument("--out-final-json", default=str(runtime.results_dir / "final_locale" / "ar.final.json"))
    parser.add_argument("--out-report", default=str(runtime.results_dir / "final_locale" / "review_fixes_report.json"))
    args = parser.parse_args()

    review_path = Path(args.review_queue)
    if not review_path.exists():
        raise SystemExit(f"Review queue not found: {review_path}")

    ar_data = base_ar_mapping(runtime)
    rows = read_simple_xlsx(review_path, required_columns=REQUIRED_REVIEW_COLUMNS)
    applied: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []

    approved_groups: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if str(row.get("status", "")).strip().lower() == "approved":
            approved_groups[(str(row.get("key", "")).strip(), str(row.get("locale", "")).strip())].append(row)

    rejected_keys: set[tuple[str, str]] = set()
    for signature, group in approved_groups.items():
        if len(group) <= 1:
            continue
        approved_values = {str(item.get("approved_new", "")) for item in group}
        reason = "duplicate_approved_rows"
        if len(approved_values) > 1:
            reason = "conflicting_approved_rows"
        rejected_keys.add(signature)
        for row in group:
            skipped.append(
                {
                    "key": str(row.get("key", "")),
                    "locale": str(row.get("locale", "")),
                    "issue_type": str(row.get("issue_type", "")),
                    "reason": reason,
                    "details": f"Rejected {len(group)} approved rows for the same key and locale.",
                }
            )

    for row in rows:
        locale = str(row.get("locale", "")).strip()
        if locale != "ar":
            continue
        status = str(row.get("status", "")).strip().lower()
        if status != "approved":
            continue
        key = str(row.get("key", "")).strip()
        if (key, locale) in rejected_keys:
            continue
        approved_new = str(row.get("approved_new", ""))
        source_old_value = str(row.get("source_old_value", ""))
        source_hash = str(row.get("source_hash", ""))
        suggested_hash = str(row.get("suggested_hash", ""))
        plan_id = str(row.get("plan_id", ""))
        generated_at = str(row.get("generated_at", ""))
        if not all((key, approved_new, source_hash, suggested_hash, plan_id, generated_at)):
            skipped.append(
                {
                    "key": key,
                    "locale": locale,
                    "issue_type": str(row.get("issue_type", "")),
                    "reason": "malformed_row",
                    "details": "Approved row is missing required integrity fields.",
                }
            )
            continue
        if compute_text_hash(approved_new) != suggested_hash:
            skipped.append(
                {
                    "key": key,
                    "locale": locale,
                    "issue_type": str(row.get("issue_type", "")),
                    "reason": "suggested_hash_mismatch",
                    "details": "Approved text does not match the recorded suggestion hash.",
                }
            )
            continue
        old_value = str(ar_data.get(key, ""))
        if old_value != source_old_value or compute_text_hash(old_value) != source_hash:
            skipped.append(
                {
                    "key": key,
                    "locale": locale,
                    "issue_type": str(row.get("issue_type", "")),
                    "reason": "stale_source",
                    "details": "Current locale value does not match the approved source snapshot.",
                }
            )
            continue
        ar_data[key] = approved_new
        applied.append(
            {
                "key": key,
                "old_value": old_value,
                "new_value": approved_new,
                "issue_type": str(row.get("issue_type", "")),
                "plan_id": plan_id,
                "generated_at": generated_at,
            }
        )

    write_json(ar_data, Path(args.out_final_json))
    write_json(
        {
            "summary": {
                "approved_rows_applied": len(applied),
                "approved_rows_skipped": len(skipped),
                "final_locale": "Results/final_locale/ar.final.json",
            },
            "applied": applied,
            "skipped": skipped,
        },
        Path(args.out_report),
    )
    print(f"Applied approved review fixes: {len(applied)}")
    print(f"Final locale: {args.out_final_json}")
    print(f"Report:       {args.out_report}")


if __name__ == "__main__":
    main()
