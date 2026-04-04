#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from l10n_audit.core.locale_exporters import export_locale_mapping
from l10n_audit.core.audit_report_utils import load_all_report_issues
from l10n_audit.core.audit_runtime import is_risky_for_whitespace_normalization, load_locale_mapping, load_runtime, write_json, write_simple_xlsx
from l10n_audit.core.decision_engine import is_routing_enabled
from l10n_audit.core.routing_metrics import RoutingMetrics

logger = logging.getLogger("l10n_audit.fixes")

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
    "dont": "don't",
    "wont": "won't",
    "cant": "can't",
    "shouldnt": "shouldn't",
    "wouldnt": "wouldn't",
    "couldnt": "couldn't",
    "doesnt": "doesn't",
    "isnt": "isn't",
    "arent": "aren't",
    "werent": "weren't",
    "wasnt": "wasn't",
    "havent": "haven't",
    "hasnt": "hasn't",
    "hadnt": "hadn't",
}


def preprocess_source_text(text: str) -> str:
    """Apply safe replacements to clean English source text before AI review."""
    if not text or not isinstance(text, str):
        return text
    result = text
    # Sort replacements by length descending to avoid partial replacements (e.g., 'cant' vs 'canot')
    sorted_replacements = sorted(SAFE_REPLACEMENTS.items(), key=lambda x: len(x[0]), reverse=True)
    for old, nxt in sorted_replacements:
        result = result.replace(old, nxt)
    return result


def is_small_safe_change(old: str, new: str) -> bool:
    if not old or not new or old == new:
        return False
    # Max 12 words for safe AI suggestion (slightly more than general safe fix)
    if len(old.split()) > 12 or len(new.split()) > 12:
        return False
    return abs(len(old) - len(new)) <= max(10, len(old) // 2)


def classify_issue(issue: dict[str, Any]) -> str:
    source = str(issue.get("source", ""))
    issue_type = str(issue.get("issue_type", ""))
    details = issue.get("details", {})
    old = str(details.get("old", issue.get("target", "")))
    new = str(details.get("new", issue.get("suggestion", "")))

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

    if source == "ai_review" or issue.get("code") == "AI_SUGGESTION":
        # AI Suggestions are safe if verified and small
        is_verified = issue.get("verified") is True or issue.get("extra", {}).get("verified") is True
        if is_verified and is_small_safe_change(old, new):
            return "auto_safe"
        return "review_required"

    if source == "icu_message_audit":
        return "review_required"

    return "review_required"


def build_fix_plan(issues: list[dict[str, Any]], project_root: Path | None = None, runtime: Any = None) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    
    # --- Priority 1: Read from Persistent Staged Storage ---
    if project_root:
        try:
            from l10n_audit.core.results_manager import get_staged_dir
            import json as _json
            staged_file = get_staged_dir(project_root) / "approved_translations.json"
            if staged_file.exists():
                staged_data = _json.loads(staged_file.read_text(encoding="utf-8"))
                for identity, data in staged_data.items():
                    key = data.get("key")
                    locale = data.get("locale")
                    candidate = data.get("suggestion")
                    if not (key and locale and candidate):
                        continue
                        
                    signature = (key, locale, candidate)
                    item = {
                        "key": key,
                        "locale": locale,
                        "source": "persistent_staged",
                        "issue_type": "verified_migration",
                        "severity": "info",
                        "classification": "auto_safe",
                        "message": "Applying previously verified translation from staged storage.",
                        "current_value": data.get("source_text", ""),
                        "candidate_value": candidate,
                        "provenance": [{"source": "persistent_staged", "issue_type": "verified_migration", "message": "Staged", "severity": "info"}],
                    }
                    seen[signature] = item
                    plan.append(item)
                logger.info("Loaded %d items from persistent staged storage.", len(seen))
        except Exception as e:
            logger.warning("Failed to load persistent staged translations: %s", e)

    from l10n_audit.core.enforcement_layer import EnforcementController
    enforcer = EnforcementController(runtime)
    
    # --- Priority 2: Audit Issues ---
    for issue in issues:
        decision = issue.get("decision", {})
        route = decision.get("route")

        enforcer.record(route)
        enforcer.record_adaptive(decision.get("confidence", 0.5), decision.get("risk", "low"))
        
        if not enforcer.should_process(route, "autofix"):
            enforcer.record_skip("autofix")
            logger.debug(
                "AUTO-FIX OPTIMIZATION: Skipping key='%s' route='%s'",
                issue.get("key"),
                route
            )
            continue
                
        # Strict security: AI suggestions MUST be verified to be included in the plan
        if issue.get("source") == "ai_review" or issue.get("code") == "AI_SUGGESTION" or issue.get("issue_type") == "ai_suggestion":
            is_verified = issue.get("verified") is True or issue.get("extra", {}).get("verified") is True
            if not is_verified:
                logger.debug("Skipping unverified AI suggestion for key: %s", issue.get("key"))
                continue

        details = issue.get("details", {})
        key = str(issue.get("key", ""))
        locale = "en" if issue.get("source") in {"locale_qc", "grammar"} else str(issue.get("locale", ""))
        if issue.get("source") == "ar_locale_qc":
            locale = "ar"
            
        candidate = str(issue.get("approved_new") or issue.get("suggested_fix") or details.get("new") or issue.get("suggestion") or "").strip()
        current = str(issue.get("source_old_value") or issue.get("target") or details.get("old") or issue.get("current_translation") or "").strip()
        
        classification = classify_issue(issue)
        signature = (key, locale, candidate)
        
        provenance = {
            "source": str(issue.get("source", "")),
            "issue_type": str(issue.get("issue_type", "")),
            "message": str(issue.get("message", "")),
            "severity": str(issue.get("severity", "")),
        }
        
        if signature in seen:
            if provenance not in seen[signature]["provenance"]:
                seen[signature]["provenance"].append(provenance)
            continue
            
        item = {
            "key": key,
            "locale": locale,
            "source": str(issue.get("source", "")),
            "issue_type": str(issue.get("issue_type", "")),
            "severity": str(issue.get("severity", "")),
            "classification": classification,
            "message": str(issue.get("message", "")),
            "current_value": current,
            "candidate_value": candidate,
            "provenance": [provenance],
        }
        seen[signature] = item
        plan.append(item)
        
    if is_routing_enabled(runtime):
        # Expose legacy info message to ensure log format persists
        logger.info("Routing Metrics [apply_safe_fixes]: %s", enforcer.metrics.to_dict())
        enforcer.save_metrics(runtime)
        
    return plan


def apply_safe_changes(data: dict[str, object], plan: list[dict[str, Any]], locale: str, excluded_keys: set[str] | None = None, *, runtime: object = None) -> tuple[dict[str, object], list[dict[str, Any]]]:
    updated = dict(data)
    applied: list[dict[str, Any]] = []
    per_key: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    
    excluded_keys = excluded_keys or set()

    for item in plan:
        if item["classification"] == "auto_safe" and item["locale"] == locale and item["candidate_value"]:
            if str(item["key"]) in excluded_keys:
                logger.debug("Skipping excluded key: %s", item["key"])
                continue
            per_key[str(item["key"])].append(item)

    rejected_items: list[dict[str, Any]] = []

    resolver = None
    if runtime is not None and locale != "ar":
        from l10n_audit.core.conflict_resolution import get_conflict_resolver, MutationRecord
        resolver = get_conflict_resolver(runtime)

    for key, items in per_key.items():
        candidates = {str(item["candidate_value"]) for item in items if item["candidate_value"]}
        if len(candidates) != 1:
            for item in items:
                item["classification"] = "review_required"
                item["message"] = f"{item['message']} Conflicting candidate values detected."
                rejected_items.extend(items)
            continue
        current_value = data.get(key)
        if not isinstance(current_value, str):
            continue
        new_value = next(iter(candidates))
        if current_value == new_value:
            continue

        # --- Phase 10: Conflict Resolution (Governance Layer) ---
        if resolver is not None:
            # We assume auto-fix items in this loop are Priority 3.
            # If offset/length are missing in the item (common for dict-based fixes),
            # MutationRecord will use fallback identity.
            first_item = items[0]
            record = MutationRecord(
                key=key,
                original_text=current_value,
                new_text=new_value,
                offset=first_item.get("offset", -1),
                length=first_item.get("error_length", 0),
                source="auto_fix",
                priority=3
            )
            if not resolver.register(record):
                logger.warning("CONFLICT DETECTED: Skipping safe fix for key '%s' due to priority overlap.", key)
                continue
        
        updated[key] = new_value
        applied.extend(items)
        
        # Log success
        source_info = items[0]["source"]
        logger.info("Applied safe fix for key '%s' (%s) - verified by %s", key, locale, source_info)

    # --- Phase 10: Metrics Injection ---
    if resolver is not None and runtime is not None:
        try:
            if hasattr(runtime, "metadata"):
                runtime.metadata["conflict_metrics"] = resolver.summarize()
        except Exception:
            pass

    # --- Phase 8: Feedback Signal Capture (observational only) ---
    try:
        aggregator = getattr(runtime, "_feedback_aggregator", None) if runtime is not None else None
        if aggregator is not None:
            from l10n_audit.core.feedback_engine import FeedbackSignal
            for item in applied:
                decision = item.get("decision", {})
                aggregator.record(FeedbackSignal(
                    route=decision.get("route", "auto_fix"),
                    confidence=float(decision.get("confidence", 0.5)),
                    risk=str(decision.get("risk", "low")),
                    was_accepted=True,
                    was_modified=False,
                    was_rejected=False,
                    source="autofix",
                ))
            for item in rejected_items:
                decision = item.get("decision", {})
                aggregator.record(FeedbackSignal(
                    route=decision.get("route", "auto_fix"),
                    confidence=float(decision.get("confidence", 0.5)),
                    risk=str(decision.get("risk", "low")),
                    was_accepted=False,
                    was_modified=False,
                    was_rejected=True,
                    source="autofix",
                ))
    except Exception:
        pass  # Feedback capture is best-effort; never affects apply behavior

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
        normalized = re.sub(r" {2,}", " ", trimmed)
        if normalized != trimmed and not is_risky_for_whitespace_normalization(value):
            rows.append(
                {
                    "key": key,
                    "locale": locale,
                    "source": "direct_scan",
                    "issue_type": "spacing",
                    "severity": "low",
                    "classification": "auto_safe",
                    "message": "Normalize repeated ASCII spaces.",
                    "current_value": value,
                    "candidate_value": normalized,
                    "provenance": [{"source": "direct_scan", "issue_type": "spacing", "message": "Normalize repeated ASCII spaces.", "severity": "low"}],
                }
            )
        if locale == "en":
            lowered = normalized
            for before, after in SAFE_REPLACEMENTS.items():
                if before in lowered and before != after and not is_risky_for_whitespace_normalization(value):
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
                            "provenance": [{"source": "direct_scan", "issue_type": "known_safe_replacement", "message": f"Apply known safe replacement: {before} -> {after}", "severity": "low"}],
                        }
                    )
    return rows


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-plan-json", default=str(runtime.results_dir / ".cache" / "apply" / "fix_plan.json"))
    parser.add_argument("--out-plan-xlsx", default=str(runtime.results_dir / ".cache" / "apply" / "fix_plan.xlsx"))
    parser.add_argument("--out-applied-report", default=str(runtime.results_dir / ".cache" / "apply" / "safe_fixes_applied_report.json"))
    parser.add_argument("--out-en-fixed", default=str(runtime.results_dir / ".cache" / "apply" / "en.fixed.json"))
    parser.add_argument("--out-ar-fixed", default=str(runtime.results_dir / ".cache" / "apply" / "ar.fixed.json"))
    parser.add_argument("--out-exports-dir", default=str(runtime.results_dir / "exports"))
    args = parser.parse_args()

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    ar_data = load_locale_mapping(runtime.ar_file, runtime, target_locale)
    _reports, issues, _missing = load_all_report_issues(runtime.results_dir)

    plan = build_fix_plan(issues, runtime.project_root, runtime)
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


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options, **_) -> list:
    """Apply safe fixes to locale files and return a dummy issue list.
    
    Returns an empty list as this stage performs side-effects (writes files).
    """
    from l10n_audit.models import issue_from_dict
    from l10n_audit.core.audit_report_utils import load_all_report_issues
    from l10n_audit.core.locale_exporters import export_locale_mapping
    from l10n_audit.core.audit_runtime import load_locale_mapping, write_json, write_simple_xlsx

    results_dir = options.effective_output_dir(runtime.results_dir)
    fixes_dir = results_dir / ".cache" / "apply"
    exports_dir = results_dir / "exports"
    fixes_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    ar_data = load_locale_mapping(runtime.ar_file, runtime, target_locale)
    
    _reports, issues, _missing = load_all_report_issues(results_dir)

    plan = build_fix_plan(issues, runtime.project_root, runtime)
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

    # Exclude paths logic
    excluded_paths = [Path(p) for p in (options.excluded_paths or [])]
    excluded_keys = set()
    
    # Simple check: if any issue's 'file' or 'path' is in excluded_paths, exclude its key
    for issue in issues:
        file_path = issue.get("file") or issue.get("path")
        if file_path:
            abs_file = Path(file_path).resolve()
            for exc_p in excluded_paths:
                if abs_file == exc_p.resolve() or str(abs_file).startswith(str(exc_p.resolve())):
                    excluded_keys.add(issue.get("key"))
                    break

    fixed_en, applied_en = apply_safe_changes(en_data, unique, "en", excluded_keys=excluded_keys)
    fixed_ar, applied_ar = apply_safe_changes(ar_data, unique, "ar", excluded_keys=excluded_keys)

    
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

    # Write results
    out_en_fixed = fixes_dir / "en.fixed.json"
    out_ar_fixed = fixes_dir / "ar.fixed.json"
    out_en_fixed.write_text(__import__("json").dumps(fixed_en, ensure_ascii=False, indent=2), encoding="utf-8")
    out_ar_fixed.write_text(__import__("json").dumps(fixed_ar, ensure_ascii=False, indent=2), encoding="utf-8")

    if runtime.locale_format == "laravel_php":
        export_locale_mapping(fixed_en, runtime.locale_format, exports_dir / runtime.source_locale)
        export_locale_mapping(fixed_ar, runtime.locale_format, exports_dir / target_locale)
    else:
        export_locale_mapping(fixed_en, "json", exports_dir / f"{runtime.source_locale}.json")
        export_locale_mapping(fixed_ar, "json", exports_dir / f"{target_locale}.json")

    write_json({"summary": {"total_items": len(unique)}, "plan": unique}, fixes_dir / "fix_plan.json")
    write_json({"keys_auto_fixed": applied_en + applied_ar}, fixes_dir / "safe_fixes_applied_report.json")
    if options.suppression.include_fix_plan_xlsx:
        write_simple_xlsx(unique, ["key", "locale", "source", "issue_type", "severity", "classification", "message", "current_value", "candidate_value"], fixes_dir / "fix_plan.xlsx")
    else:
        import logging as _logging
        _logging.getLogger("l10n_audit.apply_safe_fixes").debug("Skipped writing fix_plan.xlsx (include_fix_plan_xlsx=False)")

    return []


if __name__ == "__main__":
    main()
