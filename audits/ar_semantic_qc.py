#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from core.context_evaluator import (
    build_context_bundle,
    build_language_tool_python_signals,
    english_sentence_shape,
    load_en_languagetool_signals,
    merge_linguistic_signals,
)
from core.audit_runtime import load_locale_mapping, load_runtime, write_csv, write_json, write_simple_xlsx
from core.usage_scanner import scan_code_usage

ACTION_SUGGESTIONS = {
    "save": "احفظ",
    "add": "أضف",
    "send": "أرسل",
    "select": "اختر",
    "enter": "أدخل",
    "approve": "وافق على",
    "delete": "احذف",
}


def make_finding(
    key: str,
    issue_type: str,
    severity: str,
    message: str,
    old: str,
    *,
    candidate_value: str = "",
    suggestion_confidence: str = "low",
    review_reason: str = "",
    context_bundle: dict[str, object] | None = None,
) -> dict[str, str]:
    bundle = context_bundle or {}
    return {
        "key": key,
        "issue_type": issue_type,
        "severity": severity,
        "message": message,
        "old": old,
        "candidate_value": candidate_value,
        "fix_mode": "review_required",
        "suggestion_confidence": suggestion_confidence,
        "audit_source": "ar_semantic_qc",
        "context_type": str(bundle.get("inferred_text_type", "")),
        "ui_surface": str(bundle.get("ui_surface", "")),
        "text_role": str(bundle.get("text_role", "")),
        "action_hint": str(bundle.get("action_hint", "")),
        "audience_hint": str(bundle.get("audience_hint", "")),
        "context_flags": "|".join(str(item) for item in bundle.get("context_sensitive_term_flags", [])),
        "semantic_risk": str(bundle.get("semantic_risk", "low")),
        "lt_signals": str(bundle.get("linguistic_signals", {})),
        "review_reason": review_reason or str(bundle.get("review_reason", "")),
    }


def build_semantic_candidate(en_text: str, ar_text: str, bundle: dict[str, object]) -> tuple[str, str]:
    english_lower = en_text.casefold()
    semantic_flags = [str(item) for item in bundle.get("semantic_flags", [])]
    if any(flag in {"role_entity_misalignment", "structural_mismatch"} for flag in semantic_flags):
        return "", "low"
    if str(bundle.get("semantic_risk", "low")) == "high":
        return "", "low"

    missing_actions = [flag.split(":", 1)[1] for flag in semantic_flags if flag.startswith("missing_action:")]
    if not missing_actions:
        return "", "low"

    action = missing_actions[0]
    arabic_verb = ACTION_SUGGESTIONS.get(action)
    if not arabic_verb:
        return "", "low"
    if arabic_verb in ar_text:
        return "", "low"

    candidate = f"{arabic_verb} {ar_text.strip()}".strip()
    if english_sentence_shape(en_text) == "sentence_like" and not candidate.endswith((".", "!", "؟")):
        candidate = f"{candidate}."
    return candidate, "medium"


def detect_semantic_findings(key: str, en_text: str, ar_text: str, bundle: dict[str, object]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    english_shape = str(bundle.get("english_sentence_shape", ""))
    arabic_shape = str(bundle.get("arabic_sentence_shape", ""))
    text_role = str(bundle.get("text_role", ""))
    semantic_flags = [str(item) for item in bundle.get("semantic_flags", [])]
    candidate_value, confidence = build_semantic_candidate(en_text, ar_text, bundle)

    if english_shape == "sentence_like" and arabic_shape == "short_label":
        findings.append(
            make_finding(
                key,
                "sentence_shape_mismatch",
                "medium",
                "English source is sentence-like, but the Arabic text appears too short to preserve the full message.",
                ar_text,
                candidate_value=candidate_value,
                suggestion_confidence=confidence,
                context_bundle=bundle,
            )
        )

    if text_role == "message" and english_shape == "sentence_like" and arabic_shape == "short_label":
        findings.append(
            make_finding(
                key,
                "message_label_mismatch",
                "medium",
                "The Arabic text looks like a label while the source behaves like a UI message or instruction.",
                ar_text,
                candidate_value=candidate_value,
                suggestion_confidence=confidence,
                context_bundle=bundle,
            )
        )

    missing_actions = [flag.split(":", 1)[1] for flag in semantic_flags if flag.startswith("missing_action:")]
    if missing_actions:
        findings.append(
            make_finding(
                key,
                "possible_meaning_loss",
                "medium",
                f"Arabic text may be missing action meaning from the English sentence: {', '.join(sorted(set(missing_actions)))}.",
                ar_text,
                candidate_value=candidate_value,
                suggestion_confidence=confidence,
                context_bundle=bundle,
            )
        )

    if bundle.get("has_context_sensitive_terms") and any(flag.startswith(("en:", "ar_person:", "ar_entity:")) for flag in semantic_flags):
        findings.append(
            make_finding(
                key,
                "context_sensitive_meaning",
                "info",
                "This English/Arabic pair contains role or entity ambiguity. Keep semantic rewrites in manual review.",
                ar_text,
                context_bundle=bundle,
            )
        )
    return findings


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(runtime.ar_file))
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "ar_semantic_qc" / "ar_semantic_qc_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / "per_tool" / "ar_semantic_qc" / "ar_semantic_qc_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / "per_tool" / "ar_semantic_qc" / "ar_semantic_qc_report.xlsx"))
    args = parser.parse_args()

    ar_data = load_locale_mapping(Path(args.input), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    en_data = load_locale_mapping(Path(args.en), runtime, runtime.source_locale)
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

    rows: list[dict[str, str]] = []
    for key, ar_value in ar_data.items():
        en_value = en_data.get(key)
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        if not en_value.strip() or not ar_value.strip():
            continue
        bundle = build_context_bundle(
            key,
            en_value,
            ar_value,
            usage_locations=list(usage_contexts.get(key, [])),
            usage_metadata=usage_metadata.get(key),
            linguistic_signals=lt_signals.get(key),
        )
        rows.extend(detect_semantic_findings(key, en_value, ar_value, bundle))

    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"]))
    payload = {
        "input_file": str(Path(args.input).resolve()),
        "en_file": str(Path(args.en).resolve()),
        "summary": {
            "keys_scanned": len(ar_data),
            "findings": len(rows),
            "issue_types": dict(sorted(Counter(row["issue_type"] for row in rows).items())),
        },
        "findings": rows,
    }
    fieldnames = [
        "key",
        "issue_type",
        "severity",
        "message",
        "old",
        "candidate_value",
        "fix_mode",
        "suggestion_confidence",
        "audit_source",
        "context_type",
        "ui_surface",
        "text_role",
        "action_hint",
        "audience_hint",
        "context_flags",
        "semantic_risk",
        "lt_signals",
        "review_reason",
    ]
    write_json(payload, Path(args.out_json))
    write_csv(rows, fieldnames, Path(args.out_csv))
    write_simple_xlsx(rows, fieldnames, Path(args.out_xlsx), sheet_name="AR Semantic QC")
    print(f"Done. Arabic semantic QC issues found: {len(rows)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()
