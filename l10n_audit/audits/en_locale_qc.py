#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

from l10n_audit.core.audit_runtime import (
    extract_placeholders,
    is_likely_technical_text,
    is_risky_for_whitespace_normalization,
    load_json_dict,
    load_locale_mapping,
    load_runtime,
    write_csv,
    write_json,
    write_simple_xlsx,
)

RULES = [
    {"type": "grammar", "pattern": r"\b[Pp]assword is mismatch\b", "replace": "Passwords do not match", "message": "Incorrect grammar."},
    {"type": "grammar", "pattern": r"\b[Yy]our payment is successfully done\b", "replace": "Your payment was successful", "message": "Unnatural passive construction."},
    {"type": "grammar", "pattern": r"\b[Yy]our payment is failed\b", "replace": "Your payment failed", "message": "Incorrect grammar."},
    {"type": "grammar", "pattern": r"\b[Yy]our payment is cancelled\b", "replace": "Your payment was cancelled", "message": "Incorrect grammar."},
    {"type": "grammar", "pattern": r"\b[Cc]ontact with\b", "replace": "Contact", "message": "Use 'contact' instead of 'contact with'."},
    {"type": "grammar", "pattern": r"\b[Tt]alk with\b", "replace": "Talk to", "message": "Use 'talk to' instead of 'talk with'."},
    {"type": "grammar", "pattern": r"\b[Ee]nter valid email address\b", "replace": "Enter a valid email address", "message": "Missing article."},
    {"type": "grammar", "pattern": r"\b[Ee]nter valid email\b", "replace": "Enter a valid email", "message": "Missing article."},
    {"type": "grammar", "pattern": r"\b[Yy]ou can not\b", "replace": "You cannot", "message": "Use 'cannot' as one word."},
    {"type": "grammar", "pattern": r"\b[Dd]idn['’]t customer arrived\?", "replace": "Has the customer arrived?", "message": "Incorrect question structure."},
    {"type": "grammar", "pattern": r"\b[Yy]ou are not reached destination\b", "replace": "You have not reached the destination", "message": "Incorrect tense and missing article."},
    {"type": "grammar", "pattern": r"\b[Pp]lease fill all the field\b", "replace": "Please fill all the fields", "message": "Singular/plural issue."},
    {"type": "grammar", "pattern": r"\b[Tt]ry few minute latter\b", "replace": "Try again in a few minutes", "message": "Incorrect grammar and spelling."},
    {"type": "grammar", "pattern": r"\b[Tt]ypically the support team send you any feedback in\b", "replace": "Typically, the support team sends you feedback within", "message": "Verb agreement and unnatural wording."},
    {"type": "grammar", "pattern": r"\b[Ss]earching a car to go your destination\?", "replace": "Looking for a car to reach your destination?", "message": "Incorrect wording."},
    {"type": "grammar", "pattern": r"\b[Yy]our car is arrived be ready for your trip\b", "replace": "Your car has arrived. Be ready for your trip.", "message": "Incorrect tense and punctuation."},
    {"type": "grammar", "pattern": r"\b[Ee]njoy Your Ride ! & travel your destination everyday\b", "replace": "Enjoy your ride and travel to your destination every day.", "message": "Incorrect wording, punctuation, and spelling."},
    {"type": "grammar", "pattern": r"\b[Yy]our have to reach your pickup point in counting time\b", "replace": "You have to reach your pickup point within the countdown time", "message": "Incorrect grammar."},
    {"type": "grammar", "pattern": r"\b[Ff]or feel better experience\b", "replace": "For a better experience", "message": "Incorrect grammar."},
    {"type": "grammar", "pattern": r"\b[Ee]nd this trip is\b", "replace": "End this trip at", "message": "Incorrect wording."},
    {"type": "grammar", "pattern": r"\b[Yy]ou are now out of our service area\. Without our service area you don[’']t find any new trip request or search for new request\.", "replace": "You are now outside our service area. You will not receive new trip requests here.", "message": "Incorrect grammar and unnatural wording."},
    {"type": "grammar", "pattern": r"\b[Tt]o get request, must stay in our coverage area\.", "replace": "To receive requests, you must stay within our coverage area.", "message": "Missing subject and article."},
    {"type": "grammar", "pattern": r"\b[Uu]ntil wow you can[’']t solve your safety issue\b", "replace": "If your safety issue is not resolved", "message": "Incorrect wording."},
    {"type": "grammar", "pattern": r"\b[Hh]ere a list of numbers that you may contact\.", "replace": "Here is a list of numbers you may contact.", "message": "Missing verb."},
    {"type": "grammar", "pattern": r"\b[Yy]ou will be logout from your panel\.", "replace": "You will be logged out from your panel.", "message": "Incorrect verb form."},
    {"type": "grammar", "pattern": r"\b[Ii]dentification content need verification first\.", "replace": "Identification information needs verification first.", "message": "Verb agreement and wording."},
    {"type": "spelling", "pattern": r"\ballmost\b", "replace": "almost", "message": "Misspelling."},
    {"type": "spelling", "pattern": r"\bcanot\b", "replace": "cannot", "message": "Misspelling."},
    {"type": "spelling", "pattern": r"\bvarification\b", "replace": "verification", "message": "Misspelling."},
    {"type": "spelling", "pattern": r"\bratting\b", "replace": "rating", "message": "Misspelling."},
    {"type": "spelling", "pattern": r"\bpont\b", "replace": "point", "message": "Misspelling."},
    {"type": "spacing", "pattern": r"\b2hours\b", "replace": "2 hours", "message": "Missing space."},
    {"type": "style", "pattern": r"\beveryday\b", "replace": "every day", "message": "Use 'every day' for adverbial meaning."},
    {"type": "ui_wording", "pattern": r"\bCustomer Are Surrounding You!?", "replace": "Customers are nearby!", "message": "Unnatural UI wording."},
    {"type": "ui_wording", "pattern": r"\bCustomer Bided\b", "replace": "Customer placed a bid", "message": "Incorrect word form."},
    {"type": "ui_wording", "pattern": r"\b[Yy]our Trip is Accepted\b", "replace": "Your trip has been accepted", "message": "Unnatural UI wording."},
    {"type": "ui_wording", "pattern": r"\bStay online mode to get more ride\b", "replace": "Stay online to get more rides", "message": "Unnatural wording."},
]


def severity_for_issue(issue_type: str, severity: str | None = None) -> str:
    if severity:
        normalized = severity.lower()
        return "medium" if normalized == "warning" else normalized
    if issue_type in {"grammar", "ui_wording"}:
        return "medium"
    if issue_type in {"spacing", "style", "spelling", "capitalization"}:
        return "low"
    if issue_type in {"key_naming", "placeholder_mismatch"}:
        return "high"
    return "info"


def make_finding(key: str, issue_type: str, message: str, old: str, new: str = "", severity: str = "", related: str = "") -> dict[str, str]:
    return {
        "key": key,
        "issue_type": issue_type,
        "severity": severity_for_issue(issue_type, severity),
        "message": message,
        "old": old,
        "new": new,
        "related": related,
    }


def apply_rules(key: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for rule in RULES:
        if re.search(rule["pattern"], text, flags=re.IGNORECASE):
            findings.append(
                make_finding(
                    key=key,
                    issue_type=rule["type"],
                    message=rule["message"],
                    old=text,
                    new=re.sub(rule["pattern"], rule["replace"], text, flags=re.IGNORECASE),
                )
            )
    return findings


def key_name_issues(key: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    replacements = [("ratting", "rating"), ("pont", "point"), ("canot", "cannot")]
    for bad, good in replacements:
        if bad in key:
            findings.append(make_finding(key, "key_naming", "Misspelling in key name.", key, key.replace(bad, good)))
    return findings


def detect_capitalization_issue(key: str, text: str) -> dict[str, str] | None:
    stripped = text.strip()
    if not stripped or not re.search(r"[A-Za-z]", stripped):
        return None
    if is_likely_technical_text(stripped) or any(token in stripped for token in {"<", ">", "{", "}", "%", "$"}):
        return None
    words = re.findall(r"[A-Za-z][A-Za-z']*", stripped)
    capitalized_words = [word for word in words if word[0].isupper()]
    if len(words) >= 4 and len(capitalized_words) == len(words):
        normalized = " ".join(word.capitalize() if word.upper() != word else word for word in stripped.split())
        if normalized != stripped:
            return make_finding(key, "capitalization", "Title case used in a sentence-like string.", text, normalized)
    if stripped[0].islower() and len(words) >= 2 and any(ch in stripped for ch in ".?!"):
        return make_finding(key, "capitalization", "Sentence starts with a lowercase letter.", text, stripped[:1].upper() + stripped[1:])
    return None


def dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        signature = (row["key"], row["issue_type"], row["message"], row["old"], row["new"])
        if signature not in seen:
            seen.add(signature)
            deduped.append(row)
    return deduped


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / ".cache" / "raw_tools" / "en_locale_qc" / "en_locale_qc_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / ".cache" / "raw_tools" / "en_locale_qc" / "en_locale_qc_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / ".cache" / "raw_tools" / "en_locale_qc" / "en_locale_qc_report.xlsx"))
    args = parser.parse_args()

    en_data = load_locale_mapping(Path(args.input), runtime, runtime.source_locale)
    ar_data = load_locale_mapping(Path(args.ar), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    rows: list[dict[str, str]] = []

    duplicates: defaultdict[str, list[str]] = defaultdict(list)
    case_variants: defaultdict[str, set[str]] = defaultdict(set)
    placeholder_mismatches = 0

    for key, value in en_data.items():
        if isinstance(value, str):
            text = value
            trimmed = text.strip()
            if not is_likely_technical_text(text) and "<" not in text and ">" not in text:
                rows.extend(apply_rules(key, text))

            if text != trimmed:
                rows.append(make_finding(key, "whitespace", "Leading or trailing whitespace.", text, trimmed))
            if "  " in text and not is_risky_for_whitespace_normalization(text):
                rows.append(make_finding(key, "spacing", "Contains repeated internal spaces.", text, re.sub(r" {2,}", " ", text)))

            capitalization = detect_capitalization_issue(key, text)
            if capitalization:
                rows.append(capitalization)

            if trimmed and len(trimmed) >= 5:
                duplicates[trimmed.casefold()].append(key)
                case_variants[trimmed.casefold()].add(trimmed)

            en_placeholders = sorted(extract_placeholders(text))
            ar_placeholders = sorted(extract_placeholders(str(ar_data.get(key, ""))))
            if en_placeholders != ar_placeholders:
                placeholder_mismatches += 1
                rows.append(
                    make_finding(
                        key,
                        "placeholder_mismatch",
                        "English and Arabic placeholders differ.",
                        ", ".join(en_placeholders) or "(none)",
                        ", ".join(ar_placeholders) or "(none)",
                        related="ar.json",
                    )
                )

        rows.extend(key_name_issues(key))

    for normalized, keys in duplicates.items():
        unique_keys = sorted(set(keys))
        if len(unique_keys) > 1:
            example_value = next(iter(case_variants[normalized]))
            rows.append(
                make_finding(
                    unique_keys[0],
                    "duplicate_value",
                    f"Same English translation reused by multiple keys: {', '.join(unique_keys)}",
                    example_value,
                    related=", ".join(unique_keys[1:]),
                    severity="info",
                )
            )
        if len(case_variants[normalized]) > 1:
            variants = sorted(case_variants[normalized])
            rows.append(
                make_finding(
                    sorted(set(keys))[0],
                    "capitalization_inconsistency",
                    "Same normalized text appears with different capitalization.",
                    " | ".join(variants),
                    variants[0],
                )
            )

    rows = dedupe_rows(rows)
    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"]))

    issue_counts = Counter(row["issue_type"] for row in rows)
    payload = {
        "input_file": str(Path(args.input).resolve()),
        "ar_file": str(Path(args.ar).resolve()),
        "summary": {
            "keys_scanned": len(en_data),
            "findings": len(rows),
            "placeholder_mismatches": placeholder_mismatches,
            "issue_types": dict(sorted(issue_counts.items())),
        },
        "findings": rows,
    }

    fieldnames = ["key", "issue_type", "severity", "message", "old", "new", "related"]
    write_json(payload, Path(args.out_json))
    write_csv(rows, fieldnames, Path(args.out_csv))
    write_simple_xlsx(rows, fieldnames, Path(args.out_xlsx), sheet_name="EN Locale QC")
    print(f"Done. Issues found: {len(rows)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run the EN locale QC audit and return a list of :class:`AuditIssue`."""
    import logging
    import re
    from l10n_audit.models import issue_from_dict

    logger = logging.getLogger("l10n_audit.en_locale_qc")

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    ar_data = load_locale_mapping(
        runtime.ar_file, runtime,
        runtime.target_locales[0] if runtime.target_locales else "ar",
    )

    rows: list[dict] = []
    duplicates: dict = {}
    case_variants: dict = {}
    from collections import defaultdict
    dup_map: defaultdict = defaultdict(list)
    var_map: defaultdict = defaultdict(set)

    for key, value in en_data.items():
        if isinstance(value, str):
            text = value
            trimmed = text.strip()
            if not is_likely_technical_text(text) and "<" not in text and ">" not in text:
                rows.extend(apply_rules(key, text))
            if text != trimmed:
                rows.append(make_finding(key, "whitespace", "Leading or trailing whitespace.", text, trimmed))
            if "  " in text and not is_risky_for_whitespace_normalization(text):
                rows.append(make_finding(key, "spacing", "Contains repeated internal spaces.", text, re.sub(r" {2,}", " ", text)))
            capitalization = detect_capitalization_issue(key, text)
            if capitalization:
                rows.append(capitalization)
            if trimmed and len(trimmed) >= 5:
                dup_map[trimmed.casefold()].append(key)
                var_map[trimmed.casefold()].add(trimmed)
            en_phs = sorted(extract_placeholders(text))
            ar_phs = sorted(extract_placeholders(str(ar_data.get(key, ""))))
            if en_phs != ar_phs:
                rows.append(make_finding(key, "placeholder_mismatch", "English and Arabic placeholders differ.",
                                         ", ".join(en_phs) or "(none)", ", ".join(ar_phs) or "(none)", related="ar.json"))
        rows.extend(key_name_issues(key))

    for normalized, keys in dup_map.items():
        unique_keys = sorted(set(keys))
        if len(unique_keys) > 1:
            example_value = next(iter(var_map[normalized]))
            rows.append(make_finding(unique_keys[0], "duplicate_value",
                                     f"Same English translation reused by multiple keys: {', '.join(unique_keys)}",
                                     example_value, related=", ".join(unique_keys[1:]), severity="info"))

    rows = dedupe_rows(rows)
    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"]))

    if options.write_reports:
        from collections import Counter
        from l10n_audit.core.audit_runtime import write_csv, write_json, write_simple_xlsx as _write_xlsx
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / ".cache" / "raw_tools" / "locale_qc"
        fieldnames = ["key", "issue_type", "severity", "message", "old", "new", "related"]
        payload = {
            "summary": {"keys_scanned": len(en_data), "findings": len(rows),
                        "issue_types": dict(sorted(Counter(r["issue_type"] for r in rows).items()))},
            "findings": rows,
        }
        try:
            write_json(payload, out_dir / "en_locale_qc_report.json")
            if options.suppression.include_per_tool_csv:
                write_csv(rows, fieldnames, out_dir / "en_locale_qc_report.csv")
            else:
                logger.debug("Skipped writing per-tool CSV (include_per_tool_csv=False)")
            if options.suppression.include_per_tool_xlsx:
                _write_xlsx(rows, fieldnames, out_dir / "en_locale_qc_report.xlsx", sheet_name="EN Locale QC")
            else:
                logger.debug("Skipped writing per-tool XLSX (include_per_tool_xlsx=False)")
        except Exception as exc:
            logger.warning("Failed to write EN locale QC reports: %s", exc)

    normalised = [{**r, "source": "locale_qc"} for r in rows]
    logger.info("EN locale QC: %d issues", len(normalised))
    # --- Phase 7C Slice 1: normalise output shape before downstream model ---
    from l10n_audit.core.audit_output_adapter import normalize_audit_finding
    normalised = [
        normalize_audit_finding(r, audit_source="en_locale_qc", locale="en")
        for r in normalised
    ]
    return [issue_from_dict(r) for r in normalised]
