#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from l10n_audit.core.context_evaluator import (
    build_context_bundle,
    build_language_tool_python_signals,
    evaluate_candidate_change,
    load_en_languagetool_signals,
    merge_linguistic_signals,
)
from l10n_audit.core.audit_runtime import load_json_dict, load_locale_mapping, load_runtime, write_json
from l10n_audit.core.usage_scanner import scan_code_usage


def compile_term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.IGNORECASE)


def make_violation(
    key: str,
    violation_type: str,
    message: str,
    english: str,
    arabic: str,
    expected: str = "",
    found: str = "",
    term: str = "",
    severity: str = "",
    fix_mode: str = "review_required",
    context_bundle: dict[str, object] | None = None,
    review_reason: str = "",
) -> dict[str, str]:
    context_bundle = context_bundle or {}
    return {
        "key": key,
        "violation_type": violation_type,
        "severity": severity,
        "fix_mode": fix_mode,
        "message": message,
        "term_en": term,
        "expected_ar": expected,
        "found_ar": found,
        "english_value": english,
        "arabic_value": arabic,
        "context_type": str(context_bundle.get("inferred_text_type", "")),
        "ui_surface": str(context_bundle.get("ui_surface", "")),
        "text_role": str(context_bundle.get("text_role", "")),
        "action_hint": str(context_bundle.get("action_hint", "")),
        "audience_hint": str(context_bundle.get("audience_hint", "")),
        "context_flags": "|".join(str(item) for item in context_bundle.get("context_sensitive_term_flags", [])),
        "semantic_risk": str(context_bundle.get("semantic_risk", "low")),
        "lt_signals": json.dumps(context_bundle.get("linguistic_signals", {}), ensure_ascii=False, sort_keys=True),
        "review_reason": review_reason or str(context_bundle.get("review_reason", "")),
    }


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    parser.add_argument("--glossary", default=str(runtime.glossary_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "terminology" / "terminology_violations.json"))
    args = parser.parse_args()

    en_data = load_locale_mapping(Path(args.en), runtime, runtime.source_locale)
    ar_data = load_locale_mapping(Path(args.ar), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    glossary = load_json_dict(Path(args.glossary))
    usage_data = scan_code_usage(
        runtime.code_dirs,
        runtime.usage_patterns,
        runtime.allowed_extensions,
        profile=runtime.project_profile,
        locale_format=runtime.locale_format,
        locale_keys=set(en_data) | set(ar_data),
    )
    usage_contexts = usage_data.get("usage_contexts", {})
    usage_metadata = usage_data.get("usage_metadata", {})
    lt_signals = merge_linguistic_signals(
        load_en_languagetool_signals(runtime.results_dir),
        build_language_tool_python_signals(ar_data, runtime),
    )

    glossary_terms = []
    for term in glossary.get("terms", []):
        if isinstance(term, dict) and term.get("term_en") and term.get("approved_ar"):
            glossary_terms.append(
                {
                    "term_en": str(term["term_en"]),
                    "approved_ar": str(term["approved_ar"]),
                    "forbidden_ar": [str(item) for item in term.get("forbidden_ar", []) if item],
                    "pattern": compile_term_pattern(str(term["term_en"])),
                }
            )

    global_forbidden = []
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            if isinstance(item, dict) and item.get("forbidden_ar") and item.get("use_instead"):
                global_forbidden.append((str(item["forbidden_ar"]), str(item["use_instead"])))

    violations: list[dict[str, str]] = []
    for key, en_value in en_data.items():
        ar_value = ar_data.get(key, "")
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        en_text = en_value.strip()
        ar_text = ar_value.strip()
        if not en_text or not ar_text:
            continue
        context_bundle = build_context_bundle(
            key,
            en_text,
            ar_text,
            usage_locations=list(usage_contexts.get(key, [])),
            usage_metadata=usage_metadata.get(key),
            linguistic_signals=lt_signals.get(key),
        )

        for forbidden, approved in global_forbidden:
            if forbidden in ar_text:
                candidate = ar_text.replace(forbidden, approved)
                decision = evaluate_candidate_change(context_bundle, candidate)
                violations.append(
                    make_violation(
                        key,
                        "context_sensitive_term_conflict" if decision["review_required"] else "forbidden_term",
                        (
                            f"Arabic translation uses forbidden term '{forbidden}', but the replacement is context-sensitive."
                            if decision["review_required"]
                            else f"Arabic translation uses forbidden term '{forbidden}'."
                        ),
                        en_text,
                        ar_text,
                        expected="" if decision["review_required"] else approved,
                        found=forbidden,
                        severity="medium" if decision["review_required"] else "high",
                        context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                        review_reason=str(decision["review_reason"]),
                    )
                )

        for term in glossary_terms:
            if not term["pattern"].search(en_text):
                continue
            approved_ar = term["approved_ar"]
            forbidden_terms = term["forbidden_ar"]
            if approved_ar not in ar_text:
                decision = evaluate_candidate_change(context_bundle, approved_ar)
                violations.append(
                    make_violation(
                        key,
                        "context_sensitive_term_conflict" if decision["review_required"] else "soft_terminology_drift",
                        (
                            f"English references '{term['term_en']}' but the glossary replacement is context-sensitive."
                            if decision["review_required"]
                            else f"English references '{term['term_en']}' but Arabic does not use the approved glossary term."
                        ),
                        en_text,
                        ar_text,
                        expected="" if decision["review_required"] else approved_ar,
                        term=term["term_en"],
                        severity="medium" if decision["review_required"] else "low",
                        context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                        review_reason=str(decision["review_reason"]),
                    )
                )
            for forbidden in forbidden_terms:
                if forbidden in ar_text:
                    decision = evaluate_candidate_change(context_bundle, ar_text.replace(forbidden, approved_ar))
                    violations.append(
                        make_violation(
                            key,
                            "context_sensitive_term_conflict" if decision["review_required"] else "hard_violation",
                            (
                                f"English references '{term['term_en']}' but the replacement is context-sensitive."
                                if decision["review_required"]
                                else f"English references '{term['term_en']}' but Arabic uses forbidden terminology."
                            ),
                            en_text,
                            ar_text,
                            expected="" if decision["review_required"] else approved_ar,
                            found=forbidden,
                            term=term["term_en"],
                            severity="medium",
                            context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                            review_reason=str(decision["review_reason"]),
                        )
                    )

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for violation in violations:
        signature = (
            violation["key"],
            violation["violation_type"],
            violation["expected_ar"],
            violation["found_ar"],
        )
        if signature not in seen:
            seen.add(signature)
            unique.append(violation)

    unique.sort(key=lambda item: (item["violation_type"], item["key"], item["term_en"], item["found_ar"]))
    payload = {
        "glossary_file": str(Path(args.glossary).resolve()),
        "summary": {
            "findings": len(unique),
            "issue_types": dict(sorted(Counter(item["violation_type"] for item in unique).items())),
        },
        "violations": unique,
    }
    write_json(payload, Path(args.out_json))
    print(f"Done. Terminology violations found: {len(unique)}")
    print(f"JSON: {args.out_json}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run terminology audit and return a list of :class:`AuditIssue`."""
    import logging
    import re
    from l10n_audit.models import issue_from_dict
    from l10n_audit.core.context_evaluator import (
        build_context_bundle, build_language_tool_python_signals,
        evaluate_candidate_change, load_en_languagetool_signals, merge_linguistic_signals,
    )

    logger = logging.getLogger("l10n_audit.terminology")
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    glossary = load_json_dict(runtime.glossary_file) if runtime.glossary_file.exists() else {}
    usage_data = scan_code_usage(
        runtime.code_dirs, runtime.usage_patterns, runtime.allowed_extensions,
        profile=runtime.project_profile, locale_format=runtime.locale_format,
        locale_keys=set(en_data) | set(ar_data),
    )
    usage_contexts = usage_data.get("usage_contexts", {})
    usage_metadata = usage_data.get("usage_metadata", {})
    lt_signals = merge_linguistic_signals(
        load_en_languagetool_signals(runtime.results_dir),
        build_language_tool_python_signals(ar_data, runtime),
    )

    glossary_terms = []
    for term in glossary.get("terms", []):
        if isinstance(term, dict) and term.get("term_en") and term.get("approved_ar"):
            glossary_terms.append({"term_en": str(term["term_en"]), "approved_ar": str(term["approved_ar"]),
                                   "forbidden_ar": [str(i) for i in term.get("forbidden_ar", []) if i],
                                   "pattern": compile_term_pattern(str(term["term_en"]))})
    global_forbidden = []
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            if isinstance(item, dict) and item.get("forbidden_ar") and item.get("use_instead"):
                global_forbidden.append((str(item["forbidden_ar"]), str(item["use_instead"])))

    violations: list[dict] = []
    for key, en_value in en_data.items():
        ar_value = ar_data.get(key, "")
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        en_text, ar_text = en_value.strip(), ar_value.strip()
        if not en_text or not ar_text:
            continue
        context_bundle = build_context_bundle(key, en_text, ar_text,
            usage_locations=list(usage_contexts.get(key, [])),
            usage_metadata=usage_metadata.get(key), linguistic_signals=lt_signals.get(key))
        for forbidden, approved in global_forbidden:
            if forbidden in ar_text:
                candidate = ar_text.replace(forbidden, approved)
                decision = evaluate_candidate_change(context_bundle, candidate)
                violations.append(make_violation(key,
                    "context_sensitive_term_conflict" if decision["review_required"] else "forbidden_term",
                    f"Arabic translation uses forbidden term '{forbidden}'.",
                    en_text, ar_text, expected="" if decision["review_required"] else approved, found=forbidden,
                    severity="medium" if decision["review_required"] else "high",
                    context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"],
                                    "context_sensitive_term_flags": decision["context_flags"]},
                    review_reason=str(decision["review_reason"])))
        for term in glossary_terms:
            if not term["pattern"].search(en_text):
                continue
            approved_ar = term["approved_ar"]
            for forbidden in term["forbidden_ar"]:
                if forbidden in ar_text:
                    decision = evaluate_candidate_change(context_bundle, ar_text.replace(forbidden, approved_ar))
                    violations.append(make_violation(key,
                        "context_sensitive_term_conflict" if decision["review_required"] else "hard_violation",
                        f"Arabic uses forbidden term for '{term['term_en']}'.",
                        en_text, ar_text, expected="" if decision["review_required"] else approved_ar, found=forbidden,
                        term=term["term_en"], severity="medium",
                        context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"],
                                        "context_sensitive_term_flags": decision["context_flags"]},
                        review_reason=str(decision["review_reason"])))

    unique: list[dict] = []
    seen: set = set()
    for v in violations:
        sig = (v["key"], v["violation_type"], v["expected_ar"], v["found_ar"])
        if sig not in seen:
            seen.add(sig)
            unique.append(v)
    unique.sort(key=lambda item: (item["violation_type"], item["key"]))

    if options.write_reports:
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / "per_tool" / "terminology"
        payload = {"summary": {"findings": len(unique)}, "violations": unique}
        try:
            write_json(payload, out_dir / "terminology_violations.json")
        except Exception as exc:
            logger.warning("Failed to write terminology reports: %s", exc)

    normalised = [{**v, "source": "terminology", "issue_type": "terminology_violation",
                   "message": v.get("message", ""), "severity": v.get("severity", "high")} for v in unique]
    logger.info("Terminology audit: %d violations", len(normalised))
    return [issue_from_dict(r) for r in normalised]
