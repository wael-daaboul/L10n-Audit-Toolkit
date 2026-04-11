#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from l10n_audit.core.audit_runtime import load_locale_mapping, load_runtime, write_csv, write_json, write_simple_xlsx
from l10n_audit.core.languagetool_layer import LTFinding, get_languagetool_layer
from l10n_audit.core.decision_engine import DecisionContext, evaluate_findings

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


def _lt_finding_to_audit_dict(finding: LTFinding, route: str) -> dict[str, object]:
    """Convert an :class:`~l10n_audit.core.languagetool_layer.LTFinding` to
    the exact dict shape previously produced by ``build_languagetool_findings``.

    Field-by-field notes
    --------------------
    * ``issue_type`` — uses ``finding.issue_category`` (lowercase).  The only
      programmatic consumer, ``load_en_languagetool_signals``, immediately
      lowercases this field when it reads the JSON (line 146 of
      ``context_evaluator.py``), so the case change is behaviorally safe.
    * ``replacements`` — carried through verbatim via
      ``finding.replacements_str`` (populated in ``_normalize_match``).
    * ``context`` — carried through verbatim via ``finding.match_context``
      (populated in ``_normalize_match`` with the same ``clean_message``
      whitespace-collapse logic as the original code).
    * ``decision`` — (Phase 1 additive) informational routing metadata only.
    """
    return {
        "key": finding.key,
        "issue_type": finding.issue_category,   # lowercased; safe — see docstring
        "rule_id": finding.rule_id,
        "message": finding.message,
        "old": finding.original_text,
        "new": finding.suggested_text,
        "replacements": finding.replacements_str,
        "context": finding.match_context,
        "offset": finding.offset,
        "error_length": finding.error_length,
        "decision": {
            "route": route,
            "confidence": round(finding.confidence_score, 2),
            "risk": finding.risk_level,
            "engine_version": "v3",
        },
    }


def build_languagetool_findings(text_by_key: list[tuple[str, str]], runtime) -> tuple[str, list[dict[str, object]], str | None]:
    """Run LanguageTool on English text and return normalised audit dicts.

    Uses :func:`~l10n_audit.core.languagetool_layer.get_languagetool_layer`
    for session lifecycle management (Phase 1 / Step 3 integration).
    Falls back to rule-based mode if LT is unavailable.

    Behavioral contract (preserved from original implementation)
    ------------------------------------------------------------
    * Returns ``(mode, findings, note)`` unconditionally.
    * Aborts analysis on the first per-key ``check()`` exception and returns
      findings accumulated so far plus an error note (identical to the
      original abort-on-first-error semantics).
    * Closes the LT session in a ``finally`` block regardless of outcome.
    """
    from l10n_audit.core.utils import check_java_available, get_java_missing_warning
    if not check_java_available():
        return "rule-based", [], get_java_missing_warning("English")

    layer = get_languagetool_layer(runtime, "en-US")
    if layer is None:
        return "rule-based", [], "LanguageTool session unavailable."

    # Build a key→text index so we can detect errors per-key in order.
    findings: list[dict[str, object]] = []
    try:
        for key, original_text in text_by_key:
            # analyze_text_batch with strict=True re-raises on the first
            # check() exception, preserving the abort-on-first-error semantics
            # of the original implementation.
            try:
                batch = layer.analyze_text_batch([(key, original_text)], strict=True)
            except Exception as exc:
                note = f"{layer.session_note or ''} LanguageTool check failed: {clean_message(str(exc))}".strip()
                return "rule-based", findings, note
            
            # Phase 1 / Step 5: Passive Decision Boundary Seam (Shadow Mode)
            ctx = DecisionContext(findings=batch, source="en")
            result = evaluate_findings(ctx, runtime=runtime)
            
            # Phase 2.1 / Step 5: English Invariant Conservation Check
            total_in = len(batch)
            total_out = (
                len(result.auto_fix) +
                len(result.ai_review) +
                len(result.manual_review) +
                len(result.dropped)
            )
            assert total_in == total_out, f"Routing invariant violated: in={total_in}, out={total_out}"
            
            # Combine all queues to guarantee zero findings are dropped.
            indexed_batch = list(enumerate(batch))
            
            auto_fix = []
            ai_review = []
            manual_review = []
            dropped = []

            for index, finding in indexed_batch:
                if finding in result.auto_fix:
                    auto_fix.append((index, finding, "auto_fix"))
                elif finding in result.ai_review:
                    ai_review.append((index, finding, "ai_review"))
                elif finding in result.manual_review:
                    manual_review.append((index, finding, "manual_review"))
                elif finding in result.dropped:
                    dropped.append((index, finding, "dropped"))

            all_findings = (
                auto_fix +
                ai_review +
                manual_review +
                dropped
            )
            
            all_findings.sort(key=lambda x: x[0])
            
            findings.extend(
                _lt_finding_to_audit_dict(f, route) for _, f, route in all_findings
            )
    finally:
        layer.close()

    return layer.session_mode, findings, layer.session_note



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
    parser.add_argument("--out-json", default=str(runtime.results_dir / ".cache" / "raw_tools" / "grammar" / "grammar_audit_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / ".cache" / "raw_tools" / "grammar" / "grammar_audit_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / ".cache" / "raw_tools" / "grammar" / "grammar_audit_report.xlsx"))
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
        out_dir = results_dir / ".cache" / "raw_tools" / "grammar"
        fieldnames = ["key", "issue_type", "rule_id", "message", "old", "new", "replacements", "context", "offset", "error_length"]
        payload = {"summary": {"keys_scanned": len(text_by_key), "findings": len(rows)}, "findings": rows}
        try:
            write_json(payload, out_dir / "grammar_audit_report.json")
            if options.suppression.include_per_tool_csv:
                write_csv(rows, fieldnames, out_dir / "grammar_audit_report.csv")
            else:
                logger.debug("Skipped writing per-tool CSV (include_per_tool_csv=False)")
            if options.suppression.include_per_tool_xlsx:
                write_simple_xlsx(rows, fieldnames, out_dir / "grammar_audit_report.xlsx", sheet_name="Grammar Audit")
            else:
                logger.debug("Skipped writing per-tool XLSX (include_per_tool_xlsx=False)")
        except Exception as exc:
            logger.warning("Failed to write grammar audit reports: %s", exc)

    normalised = [{**r, "source": "grammar", "issue_type": str(r.get("issue_type") or "").strip() or "grammar"} for r in rows]
    logger.info("Grammar audit: %d issues", len(normalised))
    return [issue_from_dict(r) for r in normalised]
