#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from l10n_audit.core.audit_runtime import load_locale_mapping, load_runtime, write_csv, write_json, write_simple_xlsx
from l10n_audit.core.languagetool_manager import create_language_tool_session

CUSTOM_RULES = [
    (r"\bcan not\b", "cannot", "Style/grammar"),
    (r"\bis mismatch\b", "do not match", "Grammar"),
    (r"\bis failed\b", "failed", "Grammar"),
    (r"\bis cancelled\b", "was cancelled", "Grammar"),
    (r"\bcontact with\b", "contact", "Grammar"),
    (r"\btalk with\b", "talk to", "Grammar"),
    (r"\bapi\b", "API", "Capitalization"),
    (r"\beveryday\b", "every day", "Grammar"),
    (r"\b2hours\b", "2 hours", "Spacing"),
    (r"\ballmost\b", "almost", "Spelling"),
    (r"\bvarification\b", "verification", "Spelling"),
    (r"\bratting\b", "rating", "Spelling"),
    (r"\bpont\b", "point", "Spelling"),
    (r"\bcanot\b", "cannot", "Spelling"),
]


def clean_message(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip()


def build_custom_findings(key: str, text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for pattern, replacement, category in CUSTOM_RULES:
        if re.search(pattern, text, flags=re.IGNORECASE):
            findings.append(
                {
                    "key": key,
                    "issue_type": category,
                    "rule_id": f"CUSTOM::{pattern}",
                    "message": f"Matched custom rule: {pattern}",
                    "old": text,
                    "new": re.sub(pattern, replacement, text, flags=re.IGNORECASE),
                    "replacements": replacement,
                    "context": text,
                    "offset": "",
                    "error_length": "",
                }
            )
    return findings


def build_languagetool_findings(text_by_key: list[tuple[str, str]], runtime) -> tuple[str, list[dict[str, object]], str | None]:
    from l10n_audit.core.utils import check_java_available, get_java_missing_warning
    if not check_java_available():
        return "rule-based", [], get_java_missing_warning("English")
        
    session = create_language_tool_session("en-US", runtime)
    if session.tool is None:
        return "rule-based", [], session.note or "LanguageTool session unavailable."

    findings: list[dict[str, object]] = []
    try:
        for key, original_text in text_by_key:
            try:
                matches = session.tool.check(original_text)
            except Exception as exc:
                return "rule-based", findings, f"{session.note} LanguageTool check failed: {clean_message(str(exc))}".strip()
            for match in matches:
                replacements = [str(getattr(item, "value", item)) for item in getattr(match, "replacements", [])[:3]]
                offset = int(getattr(match, "offset", 0))
                error_length = int(getattr(match, "errorLength", getattr(match, "error_length", 0)))
                suggested = ""
                if replacements:
                    suggested = original_text[:offset] + replacements[0] + original_text[offset + error_length :]
                category = getattr(getattr(match, "category", None), "id", "") or "Unknown"
                context = getattr(match, "context", original_text)
                findings.append(
                    {
                        "key": key,
                        "issue_type": str(category),
                        "rule_id": str(getattr(match, "ruleId", "LANGUAGETOOL")),
                        "message": clean_message(str(getattr(match, "message", ""))),
                        "old": original_text,
                        "new": suggested,
                        "replacements": ", ".join(replacements),
                        "context": clean_message(str(context)),
                        "offset": offset,
                        "error_length": error_length,
                    }
                )
    finally:
        session.close()
    return session.mode, findings, session.note or None


def dedupe_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[object, ...]] = set()
    unique_rows: list[dict[str, object]] = []
    for row in rows:
        signature = (
            row["key"],
            row.get("rule_id", ""),
            row.get("message", ""),
            row.get("old", ""),
            row.get("new", ""),
        )
        if signature not in seen:
            seen.add(signature)
            unique_rows.append(row)
    return unique_rows


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(runtime.en_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "grammar" / "grammar_audit_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / "per_tool" / "grammar" / "grammar_audit_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / "per_tool" / "grammar" / "grammar_audit_report.xlsx"))
    args = parser.parse_args()

    data = load_locale_mapping(Path(args.input), runtime, runtime.source_locale)
    text_by_key = [(key, value.strip()) for key, value in data.items() if isinstance(value, str) and value.strip()]

    rows: list[dict[str, object]] = []
    for key, text in text_by_key:
        rows.extend(build_custom_findings(key, text))

    engine = "rule-based"
    note = None
    if text_by_key:
        engine, lt_rows, note = build_languagetool_findings(text_by_key, runtime)
        rows.extend(lt_rows)
    else:
        note = "No English strings required LanguageTool analysis."

    rows = dedupe_rows(rows)
    rows.sort(key=lambda item: (str(item["key"]), str(item.get("issue_type", "")), str(item.get("rule_id", ""))))

    fieldnames = ["key", "issue_type", "rule_id", "message", "old", "new", "replacements", "context", "offset", "error_length"]
    summary = {
        "input_file": str(Path(args.input).resolve()),
        "engine": engine,
        "engine_note": note or "",
        "keys_scanned": len(text_by_key),
        "findings": len(rows),
        "issue_types": dict(sorted(Counter(str(row["issue_type"]) for row in rows).items())),
    }
    payload = {"summary": summary, "findings": rows}

    write_json(payload, Path(args.out_json))
    write_csv(rows, fieldnames, Path(args.out_csv))
    write_simple_xlsx(rows, fieldnames, Path(args.out_xlsx), sheet_name="Grammar Audit")
    print(f"Done. Issues found: {len(rows)}")
    print(f"Engine: {engine}")
    if note:
        print(f"Note: {note}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run EN grammar audit and return a list of :class:`AuditIssue`."""
    import logging
    from l10n_audit.models import issue_from_dict

    logger = logging.getLogger("l10n_audit.grammar")
    data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    text_by_key = [(key, value.strip()) for key, value in data.items() if isinstance(value, str) and value.strip()]

    rows: list[dict] = []
    for key, text in text_by_key:
        rows.extend(build_custom_findings(key, text))

    if text_by_key:
        _engine, lt_rows, _note = build_languagetool_findings(text_by_key, runtime)
        rows.extend(lt_rows)
    rows = dedupe_rows(rows)
    rows.sort(key=lambda item: (str(item["key"]), str(item.get("issue_type", ""))))

    if options.write_reports:
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / "per_tool" / "grammar"
        fieldnames = ["key", "issue_type", "rule_id", "message", "old", "new", "replacements", "context", "offset", "error_length"]
        payload = {"summary": {"keys_scanned": len(text_by_key), "findings": len(rows)}, "findings": rows}
        try:
            write_json(payload, out_dir / "grammar_audit_report.json")
            write_csv(rows, fieldnames, out_dir / "grammar_audit_report.csv")
            write_simple_xlsx(rows, fieldnames, out_dir / "grammar_audit_report.xlsx", sheet_name="Grammar Audit")
        except Exception as exc:
            logger.warning("Failed to write grammar audit reports: %s", exc)

    normalised = [{**r, "source": "grammar", "issue_type": r.get("issue_type", "grammar")} for r in rows]
    logger.info("Grammar audit: %d issues", len(normalised))
    return [issue_from_dict(r) for r in normalised]
