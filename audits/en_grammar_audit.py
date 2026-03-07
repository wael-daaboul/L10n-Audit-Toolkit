#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from core.audit_runtime import load_locale_mapping, load_runtime, write_csv, write_json, write_simple_xlsx

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


def _extract_json_payload(stdout: str) -> dict[str, object]:
    json_start = stdout.find("{")
    if json_start < 0:
        raise ValueError("LanguageTool output did not contain JSON.")
    return json.loads(stdout[json_start:])


def build_languagetool_findings(text_by_key: list[tuple[str, str]], command_jar: Path) -> tuple[str, list[dict[str, object]], str | None]:
    if not shutil.which("java"):
        return "rule-based", [], "Java runtime not available."
    if not command_jar.exists():
        return "rule-based", [], "Local LanguageTool jar not found."

    lines = [text for _, text in text_by_key]
    if not lines:
        return "languagetool-local", [], None

    line_starts: list[int] = []
    cursor = 0
    for text in lines:
        line_starts.append(cursor)
        cursor += len(text) + 1

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write("\n".join(lines))

    try:
        command = [
            "java",
            "-jar",
            str(command_jar),
            "--json",
            "-l",
            "en-US",
            str(temp_path),
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            error_text = clean_message(result.stderr or result.stdout)
            return "rule-based", [], f"LanguageTool execution failed: {error_text}"

        payload = _extract_json_payload(result.stdout)
        matches = payload.get("matches", [])
        findings: list[dict[str, object]] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            global_offset = int(match.get("offset", 0))
            line_index = bisect_right(line_starts, global_offset) - 1
            if line_index < 0 or line_index >= len(text_by_key):
                continue
            key, original_text = text_by_key[line_index]
            local_offset = global_offset - line_starts[line_index]
            error_length = int(match.get("length", 0))
            replacements = [item.get("value", "") for item in match.get("replacements", [])[:3] if isinstance(item, dict)]
            suggested = ""
            if replacements:
                suggested = original_text[:local_offset] + replacements[0] + original_text[local_offset + error_length :]

            rule = match.get("rule", {}) if isinstance(match.get("rule"), dict) else {}
            context = match.get("context", {}) if isinstance(match.get("context"), dict) else {}
            findings.append(
                {
                    "key": key,
                    "issue_type": rule.get("issueType", "Unknown"),
                    "rule_id": rule.get("id", "LANGUAGETOOL"),
                    "message": clean_message(str(match.get("message", ""))),
                    "old": original_text,
                    "new": suggested,
                    "replacements": ", ".join(replacements),
                    "context": clean_message(str(context.get("text", original_text))),
                    "offset": local_offset,
                    "error_length": error_length,
                }
            )
        return "languagetool-local", findings, None
    finally:
        temp_path.unlink(missing_ok=True)


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
    if runtime.languagetool_dir.exists():
        engine, lt_rows, note = build_languagetool_findings(
            text_by_key,
            runtime.languagetool_dir / "languagetool-commandline.jar",
        )
        rows.extend(lt_rows)
    else:
        note = "Local LanguageTool directory not found. Used built-in rule-based grammar checks only."

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
