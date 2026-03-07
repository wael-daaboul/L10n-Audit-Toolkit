#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from core.audit_runtime import load_json_dict, load_locale_mapping, load_runtime, write_json


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
) -> dict[str, str]:
    return {
        "key": key,
        "violation_type": violation_type,
        "message": message,
        "term_en": term,
        "expected_ar": expected,
        "found_ar": found,
        "english_value": english,
        "arabic_value": arabic,
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

        for forbidden, approved in global_forbidden:
            if forbidden in ar_text:
                violations.append(
                    make_violation(
                        key,
                        "forbidden_term",
                        f"Arabic translation uses forbidden term '{forbidden}'.",
                        en_text,
                        ar_text,
                        expected=approved,
                        found=forbidden,
                    )
                )

        for term in glossary_terms:
            if not term["pattern"].search(en_text):
                continue
            approved_ar = term["approved_ar"]
            forbidden_terms = term["forbidden_ar"]
            if approved_ar not in ar_text:
                violations.append(
                    make_violation(
                        key,
                        "approved_term_missing",
                        f"English references '{term['term_en']}' but Arabic does not use the approved term.",
                        en_text,
                        ar_text,
                        expected=approved_ar,
                        term=term["term_en"],
                    )
                )
            for forbidden in forbidden_terms:
                if forbidden in ar_text:
                    violations.append(
                        make_violation(
                            key,
                            "terminology_violation",
                            f"English references '{term['term_en']}' but Arabic uses forbidden terminology.",
                            en_text,
                            ar_text,
                            expected=approved_ar,
                            found=forbidden,
                            term=term["term_en"],
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
