#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICU message validation for locale strings that use plural, select, or selectordinal syntax.

What this audit does:
- validates conservative ICU-style message structure in `en.json` and `ar.json`
- compares ICU container types, branch keys, and nested placeholders across locales
- flags syntax, completeness, and structural mismatch issues without rewriting logic

What this audit does not do:
- it does not attempt full ICU semantic interpretation
- it does not translate branch content or judge linguistic quality
- it does not auto-fix branching logic because that can change runtime behavior

Supported patterns:
- {count, plural, =0{No trips} one{1 trip} other{{count} trips}}
- {gender, select, male{He arrived} female{She arrived} other{They arrived}}
- {position, selectordinal, one{#st} two{#nd} few{#rd} other{#th}}
- nested placeholders and nested ICU messages inside branches

Severity model:
- high: icu_syntax_error, icu_branch_incomplete, icu_literal_text_only
- medium: icu_branch_mismatch, icu_placeholder_mismatch
- info: icu_suspicious_variation

Automatic fixing is intentionally limited:
- ICU logic is never rewritten automatically
- findings are emitted for review so runtime message behavior remains safe
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from l10n_audit.core.audit_runtime import load_locale_mapping, load_runtime, parse_placeholders, write_csv, write_json, write_simple_xlsx

ICU_TYPES = {"plural", "select", "selectordinal"}
PLURAL_BRANCHES = {"zero", "one", "two", "few", "many", "other"}
SELECTORDINAL_BRANCHES = {"zero", "one", "two", "few", "many", "other"}
SELECTOR_RE = re.compile(r"(?:=\d+|[A-Za-z_][A-Za-z0-9_-]*)")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class IcuNode:
    variable: str
    icu_type: str
    branches: dict[str, str]
    children: dict[str, list["IcuNode"]]
    start: int
    end: int
    raw: str


@dataclass
class ParseResult:
    nodes: list[IcuNode]
    syntax_errors: list[str]


def make_finding(
    key: str,
    issue_type: str,
    severity: str,
    message: str,
    old: str,
    new: str = "",
    related: str = "",
    fix_mode: str = "review_required",
) -> dict[str, str]:
    return {
        "key": key,
        "issue_type": issue_type,
        "severity": severity,
        "message": message,
        "old": old,
        "new": new,
        "related": related,
        "audit_source": "icu_message_audit",
        "fix_mode": fix_mode,
    }


def load_icu_config(config_path: Path) -> dict[str, bool]:
    defaults = {
        "enabled": True,
        "strict_branch_matching": True,
        "enable_selectordinal": True,
    }
    if not config_path.exists():
        return defaults
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defaults
    section = payload.get("icu_message_audit", {})
    if not isinstance(section, dict):
        return defaults
    return {
        key: bool(section.get(key, default))
        for key, default in defaults.items()
    }


def strip_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_top_level_commas(content: str, maxsplit: int = 2) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in content:
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0 and len(parts) < maxsplit:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def find_matching_brace(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def parse_icu_message(text: str, config: dict[str, bool], offset: int = 0) -> ParseResult:
    nodes: list[IcuNode] = []
    errors: list[str] = []
    index = 0

    while index < len(text):
        if text[index] != "{":
            index += 1
            continue

        closing = find_matching_brace(text, index)
        if closing == -1:
            errors.append(f"Unbalanced braces near index {offset + index}.")
            break

        raw = text[index : closing + 1]
        content = raw[1:-1]
        parts = [part.strip() for part in split_top_level_commas(content)]
        if len(parts) < 3:
            index = closing + 1
            continue

        variable, icu_type = parts[0], parts[1]
        if not IDENTIFIER_RE.fullmatch(variable):
            index = closing + 1
            continue
        if icu_type not in ICU_TYPES:
            index = closing + 1
            continue
        if icu_type == "selectordinal" and not config.get("enable_selectordinal", True):
            index = closing + 1
            continue

        branches, branch_errors = parse_icu_branches(parts[2], icu_type, config, offset + index)
        child_map: dict[str, list[IcuNode]] = {}
        for selector, branch_text in branches.items():
            branch_parse = parse_icu_message(branch_text, config, offset + index)
            child_map[selector] = branch_parse.nodes
            errors.extend(branch_parse.syntax_errors)
        errors.extend(branch_errors)
        nodes.append(
            IcuNode(
                variable=variable,
                icu_type=icu_type,
                branches=branches,
                children=child_map,
                start=offset + index,
                end=offset + closing,
                raw=raw,
            )
        )
        index = closing + 1

    return ParseResult(nodes=nodes, syntax_errors=errors)


def parse_icu_branches(body: str, icu_type: str, config: dict[str, bool], offset: int) -> tuple[dict[str, str], list[str]]:
    branches: dict[str, str] = {}
    errors: list[str] = []
    index = 0
    body_length = len(body)

    while index < body_length:
        while index < body_length and body[index].isspace():
            index += 1
        if index >= body_length:
            break

        selector_match = SELECTOR_RE.match(body, index)
        if not selector_match:
            errors.append(f"Invalid ICU branch selector near index {offset + index}.")
            break
        selector = selector_match.group(0)
        if icu_type == "plural" and not (selector in PLURAL_BRANCHES or selector.startswith("=")):
            errors.append(f"Invalid plural branch selector '{selector}'.")
        if icu_type == "selectordinal" and not config.get("enable_selectordinal", True):
            errors.append("selectordinal branch found while selectordinal auditing is disabled.")
        elif icu_type == "selectordinal" and not (selector in SELECTORDINAL_BRANCHES or selector.startswith("=")):
            errors.append(f"Invalid selectordinal branch selector '{selector}'.")

        index = selector_match.end()
        while index < body_length and body[index].isspace():
            index += 1
        if index >= body_length or body[index] != "{":
            errors.append(f"Missing branch body for selector '{selector}'.")
            break

        closing = find_matching_brace(body, index)
        if closing == -1:
            errors.append(f"Unbalanced ICU branch body for selector '{selector}'.")
            break

        branch_text = body[index + 1 : closing]
        branches[selector] = branch_text
        index = closing + 1

    if strip_ws(body) and not branches:
        errors.append("ICU message contains no parseable branches.")
    if "other" not in branches:
        errors.append("ICU message is missing the required 'other' branch.")
    return branches, errors


def branch_placeholder_signatures(text: str) -> Counter[str]:
    return Counter(str(item["canonical"]) for item in parse_placeholders(text))


def compare_node_sets(
    key: str,
    en_nodes: list[IcuNode],
    ar_nodes: list[IcuNode],
    config: dict[str, bool],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if len(en_nodes) != len(ar_nodes):
        findings.append(
            make_finding(
                key,
                "icu_branch_mismatch",
                "medium",
                "English and Arabic use a different number of ICU message blocks.",
                str(len(en_nodes)),
                str(len(ar_nodes)),
            )
        )

    for index, en_node in enumerate(en_nodes):
        if index >= len(ar_nodes):
            break
        ar_node = ar_nodes[index]

        if en_node.icu_type != ar_node.icu_type:
            findings.append(
                make_finding(
                    key,
                    "icu_branch_mismatch",
                    "medium",
                    "English and Arabic use different ICU message types for the same key.",
                    en_node.icu_type,
                    ar_node.icu_type,
                    related=f"node {index}",
                )
            )
            continue

        en_branches = set(en_node.branches)
        ar_branches = set(ar_node.branches)
        if config.get("strict_branch_matching", True) and en_branches != ar_branches:
            findings.append(
                make_finding(
                    key,
                    "icu_branch_mismatch",
                    "medium",
                    "English and Arabic ICU branches differ for the same message block.",
                    ", ".join(sorted(en_branches)) or "(none)",
                    ", ".join(sorted(ar_branches)) or "(none)",
                    related=f"{en_node.icu_type} node {index}",
                )
            )

        shared_branches = sorted(en_branches & ar_branches)
        for branch in shared_branches:
            en_placeholders = branch_placeholder_signatures(en_node.branches[branch])
            ar_placeholders = branch_placeholder_signatures(ar_node.branches[branch])
            if en_placeholders != ar_placeholders:
                findings.append(
                    make_finding(
                        key,
                        "icu_placeholder_mismatch",
                        "medium",
                        f"ICU branch '{branch}' uses different placeholders between English and Arabic.",
                        ", ".join(sorted(en_placeholders.elements())) or "(none)",
                        ", ".join(sorted(ar_placeholders.elements())) or "(none)",
                        related=f"{en_node.icu_type} node {index}",
                    )
                )

        en_signature = {
            branch: (
                tuple(sorted(branch_placeholder_signatures(en_node.branches[branch]).items())),
                len(en_node.children.get(branch, [])),
                "#" in en_node.branches[branch],
            )
            for branch in sorted(en_branches)
        }
        ar_signature = {
            branch: (
                tuple(sorted(branch_placeholder_signatures(ar_node.branches[branch]).items())),
                len(ar_node.children.get(branch, [])),
                "#" in ar_node.branches[branch],
            )
            for branch in sorted(ar_branches)
        }
        if en_node.icu_type == ar_node.icu_type and en_branches == ar_branches and en_signature != ar_signature:
            findings.append(
                make_finding(
                    key,
                    "icu_suspicious_variation",
                    "info",
                    "English and Arabic use the same ICU block shape but differ in internal structure or nested formatting.",
                    en_node.raw,
                    ar_node.raw,
                    related=f"{en_node.icu_type} node {index}",
                )
            )

        for branch in shared_branches:
            findings.extend(compare_node_sets(key, en_node.children.get(branch, []), ar_node.children.get(branch, []), config))

    return findings


def find_icu_issues_for_key(key: str, en_text: str, ar_text: str, config: dict[str, bool]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    en_parse = parse_icu_message(en_text, config)
    ar_parse = parse_icu_message(ar_text, config)

    for message in en_parse.syntax_errors:
        findings.append(
            make_finding(
                key,
                "icu_syntax_error",
                "high",
                f"English ICU syntax error: {message}",
                en_text,
                related="en.json",
            )
        )
    for message in ar_parse.syntax_errors:
        findings.append(
            make_finding(
                key,
                "icu_syntax_error",
                "high",
                f"Arabic ICU syntax error: {message}",
                ar_text,
                related="ar.json",
            )
        )

    if not en_parse.nodes and not ar_parse.nodes:
        return findings
    if en_parse.nodes and not ar_parse.nodes:
        findings.append(
            make_finding(
                key,
                "icu_literal_text_only",
                "high",
                "English uses ICU message logic but Arabic collapses to plain text or loses branching.",
                en_text,
                ar_text,
                related="ar.json",
            )
        )
        return findings
    if ar_parse.nodes and not en_parse.nodes:
        findings.append(
            make_finding(
                key,
                "icu_literal_text_only",
                "high",
                "Arabic uses ICU message logic but English is plain text or missing branching.",
                ar_text,
                en_text,
                related="en.json",
            )
        )
        return findings

    for locale_name, nodes in (("English", en_parse.nodes), ("Arabic", ar_parse.nodes)):
        for node in nodes:
            if "other" not in node.branches:
                findings.append(
                    make_finding(
                        key,
                        "icu_branch_incomplete",
                        "high",
                        f"{locale_name} ICU message is missing the required 'other' branch.",
                        node.raw,
                        related=locale_name.lower(),
                    )
                )

    findings.extend(compare_node_sets(key, en_parse.nodes, ar_parse.nodes, config))
    return dedupe_findings(findings)


def dedupe_findings(rows: list[dict[str, str]]) -> list[dict[str, str]]:
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
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "icu_message_audit" / "icu_message_audit_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / "per_tool" / "icu_message_audit" / "icu_message_audit_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / "per_tool" / "icu_message_audit" / "icu_message_audit_report.xlsx"))
    args = parser.parse_args()

    config = load_icu_config(runtime.config_dir / "config.json")
    en_data = load_locale_mapping(Path(args.en), runtime, runtime.source_locale)
    ar_data = load_locale_mapping(Path(args.ar), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    findings: list[dict[str, str]] = []
    if config.get("enabled", True):
        for key in sorted(set(en_data) | set(ar_data)):
            en_value = en_data.get(key, "")
            ar_value = ar_data.get(key, "")
            if not isinstance(en_value, str) or not isinstance(ar_value, str):
                continue
            findings.extend(find_icu_issues_for_key(key, en_value, ar_value, config))

    findings = dedupe_findings(findings)
    findings.sort(key=lambda item: (item["severity"], item["key"], item["issue_type"], item["message"]))

    payload = {
        "summary": {
            "keys_scanned": len(set(en_data) | set(ar_data)),
            "findings": len(findings),
            "issue_types": dict(sorted(Counter(item["issue_type"] for item in findings).items())),
            "enabled": config.get("enabled", True),
        },
        "findings": findings,
    }

    fieldnames = ["key", "issue_type", "severity", "message", "old", "new", "related", "audit_source", "fix_mode"]
    write_json(payload, Path(args.out_json))
    write_csv(findings, fieldnames, Path(args.out_csv))
    write_simple_xlsx(findings, fieldnames, Path(args.out_xlsx), sheet_name="ICU Audit")
    print(f"Done. ICU message issues found: {len(findings)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run ICU message audit and return a list of :class:`AuditIssue`."""
    import logging
    from l10n_audit.models import issue_from_dict

    logger = logging.getLogger("l10n_audit.icu")
    config = load_icu_config(runtime.config_dir / "config.json")
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    findings: list[dict] = []
    if config.get("enabled", True):
        for key in sorted(set(en_data) | set(ar_data)):
            en_value = en_data.get(key, "")
            ar_value = ar_data.get(key, "")
            if not isinstance(en_value, str) or not isinstance(ar_value, str):
                continue
            findings.extend(find_icu_issues_for_key(key, en_value, ar_value, config))
    findings = dedupe_findings(findings)
    findings.sort(key=lambda item: (item["severity"], item["key"], item["issue_type"], item["message"]))

    if options.write_reports:
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / "per_tool" / "icu_message_audit"
        payload = {"summary": {"keys_scanned": len(set(en_data) | set(ar_data)), "findings": len(findings)}, "findings": findings}
        fieldnames = ["key", "issue_type", "severity", "message", "old", "new", "related", "audit_source", "fix_mode"]
        try:
            write_json(payload, out_dir / "icu_message_audit_report.json")
            write_csv(findings, fieldnames, out_dir / "icu_message_audit_report.csv")
            write_simple_xlsx(findings, fieldnames, out_dir / "icu_message_audit_report.xlsx", sheet_name="ICU Audit")
        except Exception as exc:
            logger.warning("Failed to write ICU audit reports: %s", exc)

    normalised = [{**f, "source": "icu_message_audit"} for f in findings]
    logger.info("ICU message audit: %d issues", len(normalised))
    return [issue_from_dict(f) for f in normalised]
