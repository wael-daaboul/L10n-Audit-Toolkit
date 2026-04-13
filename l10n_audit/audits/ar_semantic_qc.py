#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from l10n_audit.core.context_evaluator import (
    build_context_bundle,
    build_language_tool_python_signals,
    english_sentence_shape,
    load_en_languagetool_signals,
    merge_linguistic_signals,
)
from l10n_audit.core.audit_runtime import load_locale_mapping, load_runtime, write_csv, write_json, write_simple_xlsx
from l10n_audit.core.usage_scanner import scan_code_usage

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


def detect_semantic_findings(key: str, en_text: str, ar_text: str, bundle: dict[str, object], short_label_threshold: int = 3, glossary_approved_pairs: set[tuple[str, str]] | None = None) -> list[dict[str, str]]:
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

    # 1. Configurable word count threshold for "possible_meaning_loss"
    ar_word_count = len(ar_text.strip().split())
    
    missing_actions = [flag.split(":", 1)[1] for flag in semantic_flags if flag.startswith("missing_action:")]
    if missing_actions and ar_word_count >= short_label_threshold:
        findings.append(
            make_finding(
                key,
                "possible_meaning_loss",
                "medium",
                f"Arabic text may be missing action meaning from the English sentence: {', '.join(sorted(set(missing_actions)))}.",
                ar_text,
                candidate_value=candidate_value,
                suggestion_confidence="medium" if confidence == "medium" else "low",
                context_bundle=bundle,
            )
        )

    # 2. Glossary Integration to reduce noise in context-sensitive ambiguity
    is_glossary_approved = False
    if glossary_approved_pairs:
        # Check case-folded source matching
        pair = (en_text.strip().casefold(), ar_text.strip())
        if pair in glossary_approved_pairs:
            is_glossary_approved = True

    if not is_glossary_approved and bundle.get("has_context_sensitive_terms") and any(flag.startswith(("en:", "ar_person:", "ar_entity:")) for flag in semantic_flags):
        findings.append(
            make_finding(
                key,
                "context_sensitive_meaning",
                "info",
                "This English/Arabic pair contains role or entity ambiguity. Keep semantic rewrites in manual review.",
                ar_text,
                candidate_value="", # Disable robotic fix
                context_bundle=bundle,
            )
        )
    return findings


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(runtime.ar_file))
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_semantic_qc" / "ar_semantic_qc_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_semantic_qc" / "ar_semantic_qc_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_semantic_qc" / "ar_semantic_qc_report.xlsx"))
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
        role_identifiers=list(runtime.role_identifiers),
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
            role_identifiers=list(runtime.role_identifiers),
            entity_whitelist={k: list(v) for k, v in runtime.entity_whitelist.items()},
        )
        rows.extend(detect_semantic_findings(
            key, en_value, ar_value, bundle,
            short_label_threshold=getattr(args, "short_label_threshold", 3)
        ))

    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    apply_arabic_decision_routing(rows, suggestion_key="candidate_value")
    
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


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run AR semantic QC and return a list of :class:`AuditIssue`."""
    import logging
    from l10n_audit.models import issue_from_dict
    from l10n_audit.core.context_evaluator import (
        build_context_bundle, build_language_tool_python_signals,
        load_en_languagetool_signals, merge_linguistic_signals,
    )

    logger = logging.getLogger("l10n_audit.ar_semantic_qc")
    ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    usage_data = scan_code_usage(
        runtime.code_dirs, runtime.usage_patterns, runtime.allowed_extensions,
        profile=runtime.project_profile, locale_format=runtime.locale_format,
        locale_keys=set(en_data) | set(ar_data),
        role_identifiers=options.audit_rules.role_identifiers,
    )
    usage_contexts = usage_data.get("usage_contexts", {})
    usage_metadata = usage_data.get("usage_metadata", {})
    lt_signals = merge_linguistic_signals(
        load_en_languagetool_signals(runtime.results_dir),
        build_language_tool_python_signals(ar_data, runtime),
    )

    # 1. Prepare glossary-based semantic whitelist
    glossary_approved_pairs: set[tuple[str, str]] = set()
    try:
        glossary_path = runtime.glossary_file
        if glossary_path.exists():
            from l10n_audit.core.audit_runtime import load_json_dict
            glossary = load_json_dict(glossary_path)
            for term in glossary.get("terms", []):
                if isinstance(term, dict):
                    en = str(term.get("term_en", "")).strip().casefold()
                    ar = str(term.get("approved_ar", "")).strip()
                    if en and ar:
                        glossary_approved_pairs.add((en, ar))
    except Exception:
        pass

    rows: list[dict] = []
    for key, ar_value in ar_data.items():
        en_value = en_data.get(key)
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        if not en_value.strip() or not ar_value.strip():
            continue
        bundle = build_context_bundle(key, en_value, ar_value,
            usage_locations=list(usage_contexts.get(key, [])),
            usage_metadata=usage_metadata.get(key),
            linguistic_signals=lt_signals.get(key),
            role_identifiers=options.audit_rules.role_identifiers,
            entity_whitelist=options.audit_rules.entity_whitelist,
        )
        rows.extend(detect_semantic_findings(
            key, en_value, ar_value, bundle, 
            short_label_threshold=options.ai_review.short_label_threshold,
            glossary_approved_pairs=glossary_approved_pairs
        ))
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    apply_arabic_decision_routing(rows, suggestion_key="candidate_value")

    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"]))

    if options.write_reports:
        from collections import Counter
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / ".cache" / "raw_tools" / "ar_semantic_qc"
        payload = {"summary": {"keys_scanned": len(ar_data), "findings": len(rows),
                               "issue_types": dict(sorted(Counter(r["issue_type"] for r in rows).items()))},
                   "findings": rows}
        fieldnames = ["key","issue_type","severity","message","old","candidate_value","fix_mode",
                      "suggestion_confidence","audit_source","context_type","ui_surface","text_role",
                      "action_hint","audience_hint","context_flags","semantic_risk","lt_signals","review_reason"]
        try:
            write_json(payload, out_dir / "ar_semantic_qc_report.json")
            if options.suppression.include_per_tool_csv:
                write_csv(rows, fieldnames, out_dir / "ar_semantic_qc_report.csv")
            else:
                logger.debug("Skipped writing per-tool CSV (include_per_tool_csv=False)")
            if options.suppression.include_per_tool_xlsx:
                write_simple_xlsx(rows, fieldnames, out_dir / "ar_semantic_qc_report.xlsx", sheet_name="AR Semantic QC")
            else:
                logger.debug("Skipped writing per-tool XLSX (include_per_tool_xlsx=False)")
        except Exception as exc:
            logger.warning("Failed to write AR semantic QC reports: %s", exc)

    # -----------------------------------------------------------------------
    # Phase 11 — Controlled Enforcement, Feedback & Conflict Governance
    # Row preservation contract: len(output) == len(input) in ALL cases.
    # Enforcement and conflict logic affect row annotations only — never
    # remove rows from the output set.
    # -----------------------------------------------------------------------
    from l10n_audit.core.enforcement_layer import EnforcementController
    from l10n_audit.core.feedback_engine import FeedbackAggregator, FeedbackSignal
    from l10n_audit.core.conflict_resolution import get_conflict_resolver, MutationRecord

    enforcer = EnforcementController(runtime)
    feedback = FeedbackAggregator()
    # Shared per-run resolver — same registry used across all stages
    resolver = get_conflict_resolver(runtime)

    for idx, row in enumerate(rows):
        route = row.get("decision", {}).get("route")
        confidence = float(row.get("decision", {}).get("confidence", 0.5))
        risk = str(row.get("decision", {}).get("risk", "low"))

        enforcer.record(route)

        # --- Conflict governance (mutation authority only, row is never dropped) ---
        fix_text = row.get("candidate_value", "")
        mutation_blocked = False
        if fix_text:
            priority_map = {"auto_fix": 3, "ai_review": 2, "manual_review": 1}
            priority = priority_map.get(route or "", 1)
            mut = MutationRecord(
                key=row.get("key", ""),
                original_text=row.get("old", ""),
                new_text=fix_text,
                offset=-1,
                length=0,
                source="arabic",
                priority=priority,
                mutation_id=f"ar_semantic_qc:{idx}",
            )
            mutation_blocked = not resolver.register(mut)

        # --- Enforcement check (affects actionability annotation, not row existence) ---
        actionable = enforcer.should_process(route, "ai") and not mutation_blocked

        if not actionable:
            if not enforcer.should_process(route, "ai"):
                enforcer.record_skip("ai")
            row["enforcement_skipped"] = True
            feedback.record(FeedbackSignal(
                route=route or "unknown",
                confidence=confidence,
                risk=risk,
                was_accepted=False,
                was_modified=False,
                was_rejected=True,
                source="arabic",
            ))
        else:
            row["enforcement_skipped"] = False
            feedback.record(FeedbackSignal(
                route=route or "unknown",
                confidence=confidence,
                risk=risk,
                was_accepted=True,
                was_modified=False,
                was_rejected=False,
                source="arabic",
            ))

    # Persist metrics — namespaced to avoid overwriting other stages
    enforcer.save_metrics(runtime)
    if hasattr(runtime, "metadata"):
        runtime.metadata["feedback_metrics_ar_semantic_qc"] = feedback.summarize()
        runtime.metadata["conflict_metrics_ar_semantic_qc"] = {
            **resolver.summarize(),
            "source": "arabic",
            "stage": "ar_semantic_qc",
        }

    normalised = [{**r, "source": "ar_semantic_qc", "issue_type": str(r.get("issue_type") or "").strip() or "ar_semantic"} for r in rows]
    logger.info("AR semantic QC: %d issues (enforcement active=%s)", len(normalised), enforcer.enabled)
    # --- Phase 7C Slice 3 Part 3: normalize audit output shape before downstream model ---
    from l10n_audit.core.audit_output_adapter import normalize_audit_finding
    normalised = [
        normalize_audit_finding(r, audit_source="ar_semantic_qc", locale="ar")
        for r in normalised
    ]
    return [issue_from_dict(r) for r in normalised]

