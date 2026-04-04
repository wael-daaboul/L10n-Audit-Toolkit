#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from l10n_audit.core.audit_runtime import (
    load_locale_mapping,
    load_runtime,
    parse_placeholders,
    write_csv,
    write_json,
    write_simple_xlsx,
)


def _count_by(items: list[dict[str, object]], field: str) -> Counter[str]:
    return Counter(str(item.get(field, "")) for item in items)


def _joined(items: list[dict[str, object]], field: str) -> str:
    return ", ".join(str(item.get(field, "")) for item in items) or "(none)"


def make_finding(
    key: str,
    issue_type: str,
    severity: str,
    message: str,
    en_items: list[dict[str, object]],
    ar_items: list[dict[str, object]],
    suggestion: str = "",
) -> dict[str, str]:
    return {
        "key": key,
        "issue_type": issue_type,
        "severity": severity,
        "message": message,
        "en_placeholders": _joined(en_items, "raw"),
        "ar_placeholders": _joined(ar_items, "raw"),
        "suggestion": suggestion,
    }


def compare_placeholders(key: str, en_text: str, ar_text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    en_items = parse_placeholders(en_text)
    ar_items = parse_placeholders(ar_text)
    if not en_items and not ar_items:
        return findings

    en_canonical = _count_by(en_items, "canonical")
    ar_canonical = _count_by(ar_items, "canonical")
    en_style = _count_by(en_items, "style")
    ar_style = _count_by(ar_items, "style")
    en_named = [str(item["canonical"]) for item in en_items if str(item["style"]) != "printf"]
    ar_named = [str(item["canonical"]) for item in ar_items if str(item["style"]) != "printf"]

    rename_detected = (
        bool(en_named)
        and len(en_items) == len(ar_items)
        and len(en_named) == len(ar_named)
        and Counter(str(item["style"]) for item in en_items) == Counter(str(item["style"]) for item in ar_items)
        and set(en_named) != set(ar_named)
    )

    if rename_detected:
        findings.append(
            make_finding(
                key,
                "renamed_placeholder",
                "medium",
                "Placeholder names appear to have been renamed between locales.",
                en_items,
                ar_items,
                "Keep named placeholders identical across locales.",
            )
        )

    missing_in_ar = [] if rename_detected else sorted(name for name, count in en_canonical.items() if count > ar_canonical.get(name, 0))
    missing_in_en = [] if rename_detected else sorted(name for name, count in ar_canonical.items() if count > en_canonical.get(name, 0))
    if missing_in_ar:
        findings.append(
            make_finding(
                key,
                "missing_in_ar",
                "high",
                f"Arabic is missing placeholders present in English: {', '.join(missing_in_ar)}",
                en_items,
                ar_items,
                "Copy the missing placeholder tokens into ar.json without renaming them.",
            )
        )
    if missing_in_en:
        findings.append(
            make_finding(
                key,
                "missing_in_en",
                "high",
                f"English is missing placeholders present in Arabic: {', '.join(missing_in_en)}",
                en_items,
                ar_items,
                "Recheck the source locale and remove unintended Arabic-only placeholders.",
            )
        )

    if sum(en_canonical.values()) != sum(ar_canonical.values()):
        findings.append(
            make_finding(
                key,
                "count_mismatch",
                "high",
                "Placeholder counts differ between English and Arabic.",
                en_items,
                ar_items,
                "Keep placeholder counts identical across locales.",
            )
        )

    shared_canonical = sorted(set(en_canonical) & set(ar_canonical))
    if shared_canonical:
        shared_en_styles = {name: {str(item["style"]) for item in en_items if item["canonical"] == name} for name in shared_canonical}
        shared_ar_styles = {name: {str(item["style"]) for item in ar_items if item["canonical"] == name} for name in shared_canonical}
        style_mismatches = [name for name in shared_canonical if shared_en_styles[name] != shared_ar_styles[name]]
        if style_mismatches:
            findings.append(
                make_finding(
                    key,
                    "format_mismatch",
                    "high",
                    f"Matching placeholders use different interpolation formats: {', '.join(style_mismatches)}",
                    en_items,
                    ar_items,
                    "Use the same placeholder syntax in both locales.",
                )
            )

    en_sequence = [str(item["canonical"]) for item in en_items]
    ar_sequence = [str(item["canonical"]) for item in ar_items]
    if en_sequence and ar_sequence and Counter(en_sequence) == Counter(ar_sequence) and en_sequence != ar_sequence:
        order_severity = "low"
        risky_order_styles = {"printf", "dollar_index", "brace", "dollar_brace", "mustache"}
        if any(str(item["style"]) in risky_order_styles for item in [*en_items, *ar_items]):
            order_severity = "high"
        findings.append(
            make_finding(
                key,
                "order_mismatch",
                order_severity,
                "Placeholder order differs between locales.",
                en_items,
                ar_items,
                "Verify runtime interpolation supports reordered placeholders for this string.",
            )
        )

    if en_style and ar_style and set(en_style) != set(ar_style) and not missing_in_ar and not missing_in_en:
        findings.append(
            make_finding(
                key,
                "mixed_placeholder_style",
                "medium",
                "English and Arabic mix different placeholder style families.",
                en_items,
                ar_items,
                "Prefer one placeholder style per key across locales.",
            )
        )

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        signature = (finding["key"], finding["issue_type"], finding["message"])
        if signature not in seen:
            seen.add(signature)
            unique.append(finding)
    return unique


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / ".cache" / "raw_tools" / "placeholders" / "placeholder_audit_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / ".cache" / "raw_tools" / "placeholders" / "placeholder_audit_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / ".cache" / "raw_tools" / "placeholders" / "placeholder_audit_report.xlsx"))
    args = parser.parse_args()

    en_data = load_locale_mapping(Path(args.en), runtime, runtime.source_locale)
    ar_data = load_locale_mapping(Path(args.ar), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    findings: list[dict[str, str]] = []
    for key in sorted(set(en_data) | set(ar_data)):
        en_value = en_data.get(key, "")
        ar_value = ar_data.get(key, "")
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        findings.extend(compare_placeholders(key, en_value, ar_value))

    findings.sort(key=lambda item: (item["severity"], item["key"], item["issue_type"]))

    payload = {
        "summary": {
            "keys_scanned": len(set(en_data) | set(ar_data)),
            "findings": len(findings),
            "issue_types": dict(sorted(Counter(item["issue_type"] for item in findings).items())),
        },
        "findings": findings,
    }

    fieldnames = ["key", "issue_type", "severity", "message", "en_placeholders", "ar_placeholders", "suggestion"]
    write_json(payload, Path(args.out_json))
    write_csv(findings, fieldnames, Path(args.out_csv))
    write_simple_xlsx(findings, fieldnames, Path(args.out_xlsx), sheet_name="Placeholder Audit")
    print(f"Done. Placeholder issues found: {len(findings)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run the placeholder audit and return a list of :class:`AuditIssue`."""
    import logging
    from l10n_audit.models import issue_from_dict

    logger = logging.getLogger("l10n_audit.placeholders")

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    ar_data = load_locale_mapping(
        runtime.ar_file, runtime,
        runtime.target_locales[0] if runtime.target_locales else "ar",
    )

    findings: list[dict] = []
    for key in sorted(set(en_data) | set(ar_data)):
        en_value = en_data.get(key, "")
        ar_value = ar_data.get(key, "")
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        findings.extend(compare_placeholders(key, en_value, ar_value))

    findings.sort(key=lambda item: (item["severity"], item["key"], item["issue_type"]))

    if options.write_reports:
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / ".cache" / "raw_tools" / "placeholders"
        fieldnames = ["key", "issue_type", "severity", "message", "en_placeholders", "ar_placeholders", "suggestion"]
        payload = {
            "summary": {
                "keys_scanned": len(set(en_data) | set(ar_data)),
                "findings": len(findings),
            },
            "findings": findings,
        }
        try:
            write_json(payload, out_dir / "placeholder_audit_report.json")
            if options.suppression.include_per_tool_csv:
                write_csv(findings, fieldnames, out_dir / "placeholder_audit_report.csv")
            else:
                logger.debug("Skipped writing per-tool CSV (include_per_tool_csv=False)")
            if options.suppression.include_per_tool_xlsx:
                write_simple_xlsx(findings, fieldnames, out_dir / "placeholder_audit_report.xlsx", sheet_name="Placeholder Audit")
            else:
                logger.debug("Skipped writing per-tool XLSX (include_per_tool_xlsx=False)")
        except Exception as exc:
            logger.warning("Failed to write placeholder audit reports: %s", exc)

    # Normalise to standard field names for issue_from_dict
    normalised = [
        {**f, "issue_type": "placeholder_mismatch", "source": "placeholders"}
        for f in findings
    ]
    logger.info("Placeholder audit: %d issues", len(normalised))
    return [issue_from_dict(f) for f in normalised]
