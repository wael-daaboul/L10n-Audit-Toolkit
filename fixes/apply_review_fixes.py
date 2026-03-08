#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from pathlib import Path

from core.audit_runtime import load_locale_mapping, load_runtime, read_simple_xlsx, write_json


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
    rows = read_simple_xlsx(review_path)
    applied: list[dict[str, str]] = []

    for row in rows:
        if str(row.get("locale", "")).strip() != "ar":
            continue
        if str(row.get("status", "")).strip().lower() != "approved":
            continue
        approved_new = str(row.get("approved_new", "")).strip()
        key = str(row.get("key", "")).strip()
        if not key or not approved_new:
            continue
        old_value = str(ar_data.get(key, ""))
        ar_data[key] = approved_new
        applied.append(
            {
                "key": key,
                "old_value": old_value,
                "new_value": approved_new,
                "issue_type": str(row.get("issue_type", "")),
            }
        )

    write_json(ar_data, Path(args.out_final_json))
    write_json(
        {
            "summary": {
                "approved_rows_applied": len(applied),
                "final_locale": "Results/final_locale/ar.final.json",
            },
            "applied": applied,
        },
        Path(args.out_report),
    )
    print(f"Applied approved review fixes: {len(applied)}")
    print(f"Final locale: {args.out_final_json}")
    print(f"Report:       {args.out_report}")


if __name__ == "__main__":
    main()
