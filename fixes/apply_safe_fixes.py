#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.locale_exporters import export_locale_mapping
from core.audit_report_utils import load_all_report_issues
from core.audit_runtime import load_locale_mapping, load_runtime, write_json, write_simple_xlsx

SAFE_REPLACEMENTS = {
    "can not": "cannot",
    "2hours": "2 hours",
    "everyday": "every day",
    "api": "API",
    "allmost": "almost",
    "varification": "verification",
    "ratting": "rating",
    "pont": "point",
    "canot": "cannot",
}


def is_small_safe_change(old: str, new: str) -> bool:
    if not old or not new or old == new:
        return False
    if len(old.split()) > 8 or len(new.split()) > 8:
        return False
    return abs(len(old) - len(new)) <= max(8, len(old) // 2)


def classify_issue(issue: dict[str, Any]) -> str:
    source = str(issue.get("source", ""))
    issue_type = str(issue.get("issue_type", ""))
    details = issue.get("details", {})
    old = str(details.get("old", ""))
    new = str(details.get("new", ""))

    if source == "locale_qc":
        if issue_type in {"whitespace", "spacing"}:
            return "auto_safe"
        if issue_type in {"style", "spelling", "capitalization"} and is_small_safe_change(old, new):
            return "auto_safe"
        return "review_required"

    if source == "ar_locale_qc":
        if issue_type in {"whitespace", "spacing", "punctuation_spacing", "bracket_spacing", "slash_spacing"}:
            return "auto_safe"
        if issue_type == "english_punctuation" and is_small_safe_change(old, new):
            return "auto_safe"
        return "review_required"

    if source == "grammar":
        rule_id = str(details.get("rule_id", ""))
        if rule_id.startswith("CUSTOM::") and is_small_safe_change(old, new):
            return "auto_safe"
        return "review_required"

    if source == "icu_message_audit":
        return "review_required"

    return "review_required"


def build_fix_plan(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        details = issue.get("details", {})
        key = str(issue.get("key", ""))
        locale = "en" if issue.get("source") in {"locale_qc", "grammar"} else str(issue.get("locale", ""))
        if issue.get("source") == "ar_locale_qc":
            locale = "ar"
        candidate = str(details.get("new", ""))
        current = str(details.get("old", details.get("english_value", "")))
        classification = classify_issue(issue)
        signature = (key, locale, candidate)
        if signature in seen:
            continue
        seen.add(signature)
        plan.append(
            {
                "key": key,
                "locale": locale,
                "source": str(issue.get("source", "")),
                "issue_type": str(issue.get("issue_type", "")),
                "severity": str(issue.get("severity", "")),
                "classification": classification,
                "message": str(issue.get("message", "")),
                "current_value": current,
                "candidate_value": candidate,
            }
        )
    return plan


def apply_safe_changes(data: dict[str, object], plan: list[dict[str, Any]], locale: str) -> tuple[dict[str, object], list[dict[str, Any]]]:
    updated = dict(data)
    applied: list[dict[str, Any]] = []
    per_key: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in plan:
        if item["classification"] == "auto_safe" and item["locale"] == locale and item["candidate_value"]:
            per_key[str(item["key"])].append(item)

    for key, items in per_key.items():
        candidates = {str(item["candidate_value"]) for item in items if item["candidate_value"]}
        if len(candidates) != 1:
            for item in items:
                item["classification"] = "review_required"
                item["message"] = f"{item['message']} Conflicting candidate values detected."
            continue
        current_value = data.get(key)
        if not isinstance(current_value, str):
            continue
        new_value = next(iter(candidates))
        if current_value == new_value:
            continue
        updated[key] = new_value
        applied.extend(items)

    return updated, applied


def add_direct_locale_safety_pass(data: dict[str, object], locale: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, value in data.items():
        if not isinstance(value, str):
            continue
        trimmed = value.strip()
        if trimmed != value:
            rows.append(
                {
                    "key": key,
                    "locale": locale,
                    "source": "direct_scan",
                    "issue_type": "whitespace",
                    "severity": "low",
                    "classification": "auto_safe",
                    "message": "Trim leading/trailing whitespace.",
                    "current_value": value,
                    "candidate_value": trimmed,
                }
            )
        normalized = " ".join(trimmed.split())
        if normalized != trimmed:
            rows.append(
                {
                    "key": key,
                    "locale": locale,
                    "source": "direct_scan",
                    "issue_type": "spacing",
                    "severity": "low",
                    "classification": "auto_safe",
                    "message": "Normalize repeated internal spaces.",
                    "current_value": value,
                    "candidate_value": normalized,
                }
            )
        if locale == "en":
            lowered = normalized
            for before, after in SAFE_REPLACEMENTS.items():
                if before in lowered and before != after:
                    rows.append(
                        {
                            "key": key,
                            "locale": locale,
                            "source": "direct_scan",
                            "issue_type": "known_safe_replacement",
                            "severity": "low",
                            "classification": "auto_safe",
                            "message": f"Apply known safe replacement: {before} -> {after}",
                            "current_value": value,
                            "candidate_value": lowered.replace(before, after),
                        }
                    )
    return rows


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-plan-json", default=str(runtime.results_dir / "fixes" / "fix_plan.json"))
    parser.add_argument("--out-plan-xlsx", default=str(runtime.results_dir / "fixes" / "fix_plan.xlsx"))
    parser.add_argument("--out-applied-report", default=str(runtime.results_dir / "fixes" / "safe_fixes_applied_report.json"))
    parser.add_argument("--out-en-fixed", default=str(runtime.results_dir / "fixes" / "en.fixed.json"))
    parser.add_argument("--out-ar-fixed", default=str(runtime.results_dir / "fixes" / "ar.fixed.json"))
    parser.add_argument("--out-exports-dir", default=str(runtime.results_dir / "exports"))
    args = parser.parse_args()

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    ar_data = load_locale_mapping(runtime.ar_file, runtime, target_locale)
    _reports, issues, _missing = load_all_report_issues(runtime.results_dir)

    plan = build_fix_plan(issues)
    plan.extend(add_direct_locale_safety_pass(en_data, "en"))
    plan.extend(add_direct_locale_safety_pass(ar_data, "ar"))

    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in plan:
        signature = (
            str(item["key"]),
            str(item["locale"]),
            str(item["issue_type"]),
            str(item["candidate_value"]),
        )
        if signature not in seen:
            seen.add(signature)
            unique.append(item)

    fixed_en, applied_en = apply_safe_changes(en_data, unique, "en")
    fixed_ar, applied_ar = apply_safe_changes(ar_data, unique, "ar")
    applied_signatures = {
        (str(item["key"]), str(item["locale"]), str(item["issue_type"]), str(item["candidate_value"]))
        for item in [*applied_en, *applied_ar]
    }
    auto_safe_items = [item for item in unique if item["classification"] == "auto_safe"]
    skipped_auto_safe = [
        item
        for item in auto_safe_items
        if (str(item["key"]), str(item["locale"]), str(item["issue_type"]), str(item["candidate_value"])) not in applied_signatures
    ]
    review_required_items = [item for item in unique if item["classification"] == "review_required"]

    payload = {
        "summary": {
            "total_plan_items": len(unique),
            "auto_safe": sum(1 for item in unique if item["classification"] == "auto_safe"),
            "review_required": sum(1 for item in unique if item["classification"] == "review_required"),
            "applied_to_candidates": len(applied_en) + len(applied_ar),
            "by_source": dict(sorted(Counter(str(item["source"]) for item in unique).items())),
        },
        "plan": unique,
    }
    applied_report = {
        "summary": {
            "keys_auto_fixed": len(applied_signatures),
            "keys_skipped": len(skipped_auto_safe),
            "keys_requiring_review": len(review_required_items),
        },
        "keys_auto_fixed": applied_en + applied_ar,
        "keys_skipped": skipped_auto_safe,
        "keys_requiring_review": review_required_items,
    }

    Path(args.out_en_fixed).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_ar_fixed).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_en_fixed).write_text(__import__("json").dumps(fixed_en, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.out_ar_fixed).write_text(__import__("json").dumps(fixed_ar, ensure_ascii=False, indent=2), encoding="utf-8")

    exports_root = Path(args.out_exports_dir)
    if runtime.locale_format == "laravel_php":
        exported_en = export_locale_mapping(fixed_en, runtime.locale_format, exports_root / runtime.source_locale)
        exported_ar = export_locale_mapping(fixed_ar, runtime.locale_format, exports_root / target_locale)
    else:
        exported_en = export_locale_mapping(fixed_en, "json", exports_root / f"{runtime.source_locale}.json")
        exported_ar = export_locale_mapping(fixed_ar, "json", exports_root / f"{target_locale}.json")

    write_json(payload, Path(args.out_plan_json))
    write_json(applied_report, Path(args.out_applied_report))
    write_simple_xlsx(
        unique,
        ["key", "locale", "source", "issue_type", "severity", "classification", "message", "current_value", "candidate_value"],
        Path(args.out_plan_xlsx),
        sheet_name="Fix Plan",
    )
    print(f"Done. Fix plan items: {len(unique)}")
    print(f"Plan JSON: {args.out_plan_json}")
    print(f"Plan XLSX: {args.out_plan_xlsx}")
    print(f"Applied:   {args.out_applied_report}")
    print(f"EN fixed:   {args.out_en_fixed}")
    print(f"AR fixed:   {args.out_ar_fixed}")
    for path in [*exported_en, *exported_ar]:
        print(f"Exported:   {path}")


if __name__ == "__main__":
    main()
