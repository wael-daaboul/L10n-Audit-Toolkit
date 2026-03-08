#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Arabic locale quality checks for UI-facing `ar.json` content.

Purpose:
- catch deterministic Arabic UI quality issues without attempting deep grammar parsing
- keep findings portable, structured, and safe for aggregation and fix planning

Checks:
- safe formatting issues such as whitespace and slash spacing
- glossary-backed forbidden terminology
- mixed-script leakage and weak placeholder-like content
- conservative wording and consistency heuristics with false-positive controls

Severity model:
- high: forbidden_term
- medium: inconsistent_translation
- low: whitespace, spacing, punctuation_spacing, bracket_spacing, slash_spacing
- info: long_ui_string, similar_phrase_variation, exclamation_style, suspicious_literal_translation

Fix policy:
- auto_safe: trimming whitespace, normalizing repeated spaces, removing space before punctuation,
  tightening bracket spacing, fixing slash spacing
- review_required: terminology, wording, tone, translation consistency, and other content changes

Configuration toggles:
- config/config.json -> ar_locale_qc.enable_exclamation_style
- config/config.json -> ar_locale_qc.enable_long_ui_string
- config/config.json -> ar_locale_qc.enable_similar_phrase_variation
- config/config.json -> ar_locale_qc.enable_suspicious_literal_translation
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from core.context_evaluator import (
    build_context_bundle,
    build_language_tool_python_signals,
    evaluate_candidate_change,
    load_en_languagetool_signals,
    merge_linguistic_signals,
)
from core.audit_runtime import (
    has_html_or_xml,
    has_icu_syntax,
    is_likely_technical_text,
    is_risky_for_whitespace_normalization,
    load_json_dict,
    load_locale_mapping,
    load_runtime,
    parse_placeholders,
    write_csv,
    write_json,
    write_simple_xlsx,
)
from core.usage_scanner import scan_code_usage

ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9._+-]*\b")
URL_OR_EMAIL_RE = re.compile(r"(https?://|www\.|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})", re.IGNORECASE)
REPEATED_SPACE_RE = re.compile(r" {2,}")
SPACE_BEFORE_AR_PUNCT_RE = re.compile(r"\s+([،؛؟:!])")
SPACE_AFTER_OPENING_BRACKET_RE = re.compile(r"([\(\[\{])\s+")
SPACE_BEFORE_CLOSING_BRACKET_RE = re.compile(r"\s+([\)\]\}])")
SLASH_SPACING_RE = re.compile(r"\s*/\s*")
REPEATED_PUNCTUATION_RE = re.compile(r"([!؟?,،؛:])\1{1,}")
MIXED_PUNCTUATION_PAIRS = ((",", "،"), (";", "؛"), ("?", "؟"))
PLACEHOLDER_TEXT_RE = re.compile(r"^(todo|tbd|xxx+|lorem ipsum|placeholder|translation|test)$", re.IGNORECASE)
WEAK_ONLY_PUNCT_RE = re.compile(r"^[\W_]+$", re.UNICODE)
PUNCT_STRIP_RE = re.compile(r"[،؛؟:!,.()\[\]{}\-_/]")

ALLOWED_LATIN_TOKENS = {
    "API",
    "OTP",
    "SMS",
    "GPS",
    "PIN",
    "ID",
    "QR",
    "PDF",
    "URL",
    "FAQ",
    "WiFi",
    "wifi",
    "WhatsApp",
    "Google",
    "Apple",
    "Facebook",
    "Instagram",
    "YouTube",
    "TikTok",
    "iOS",
    "Android",
    "BeTaxi",
    "Bkash",
    "Flutterwave",
    "Liqpay",
    "Mercadopago",
    "Paymob",
    "PayPal",
    "PayTabs",
    "Paytm",
    "Razorpay",
    "SenangPay",
    "SSLCommerz",
    "Stripe",
}
ALLOWED_LATIN_TOKEN_FOLDS = {token.casefold() for token in ALLOWED_LATIN_TOKENS}
SHORT_EXCLAMATION_TRIGGER_TOKENS = ("الآن", "ابدأ", "اضغط", "سارع", "هيا", "ابدئي", "ابدأوا")

ARABIC_STOPWORDS = {
    "في",
    "من",
    "على",
    "إلى",
    "عن",
    "بعد",
    "قبل",
    "مع",
    "هذا",
    "هذه",
    "ذلك",
    "تلك",
    "تم",
    "لا",
    "لن",
    "لم",
    "يرجى",
    "الرجاء",
    "ثم",
    "أو",
    "و",
}

LITERAL_PATTERNS = [
    {
        "text": "لحظة من فضلك",
        "contexts": ("انتظر", "جاري", "يرجى", "لحظة"),
        "message": "This phrase sounds literal in compact UI text. Review whether a shorter Arabic prompt fits better.",
    },
    {
        "text": "قم ب",
        "contexts": ("قم ب", "قم بال", "قم بإ", "الرجاء"),
        "message": "The 'قم ب' construction can sound like a literal English translation. Review if a direct Arabic verb is clearer.",
    },
    {
        "text": "قم بالضغط",
        "contexts": ("اضغط", "هنا", "للمتابعة", "للاستمرار"),
        "message": "This instruction can feel literally translated. Review if a simpler Arabic action label is better.",
    },
]


def contains_arabic(text: str) -> bool:
    return bool(ARABIC_LETTER_RE.search(text))


def normalize_for_compare(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = SPACE_BEFORE_AR_PUNCT_RE.sub(r"\1", normalized)
    normalized = SPACE_AFTER_OPENING_BRACKET_RE.sub(r"\1", normalized)
    normalized = SPACE_BEFORE_CLOSING_BRACKET_RE.sub(r"\1", normalized)
    normalized = SLASH_SPACING_RE.sub("/", normalized)
    return normalized


def significant_first_token(text: str) -> str:
    tokens = re.findall(r"[\u0600-\u06FF]+", text)
    for token in tokens:
        if token not in ARABIC_STOPWORDS:
            return token
    return tokens[0] if tokens else ""


def strip_punctuation_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", PUNCT_STRIP_RE.sub(" ", text)).strip()


def load_rule_toggles(config_path: Path) -> dict[str, bool]:
    defaults = {
        "enable_exclamation_style": True,
        "enable_long_ui_string": True,
        "enable_similar_phrase_variation": True,
        "enable_suspicious_literal_translation": True,
    }
    if not config_path.exists():
        return defaults
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return defaults
    section = payload.get("ar_locale_qc", {})
    if not isinstance(section, dict):
        return defaults
    return {
        key: bool(section.get(key, default))
        for key, default in defaults.items()
    }


def make_finding(
    key: str,
    issue_type: str,
    severity: str,
    message: str,
    old: str,
    new: str = "",
    related: str = "",
    fix_mode: str = "review_required",
    context_bundle: dict[str, object] | None = None,
    review_reason: str = "",
) -> dict[str, str]:
    context_bundle = context_bundle or {}
    linguistic_signals = context_bundle.get("linguistic_signals", {}) if isinstance(context_bundle, dict) else {}
    return {
        "key": key,
        "issue_type": issue_type,
        "severity": severity,
        "message": message,
        "old": old,
        "new": new,
        "related": related,
        "audit_source": "ar_locale_qc",
        "fix_mode": fix_mode,
        "context_type": str(context_bundle.get("inferred_text_type", "")),
        "context_flags": "|".join(str(item) for item in context_bundle.get("context_sensitive_term_flags", [])),
        "semantic_risk": str(context_bundle.get("semantic_risk", "low")),
        "lt_signals": json.dumps(linguistic_signals, ensure_ascii=False, sort_keys=True),
        "review_reason": review_reason or str(context_bundle.get("review_reason", "")),
    }


def load_glossary_rules(glossary: dict[str, object]) -> tuple[list[dict[str, object]], list[tuple[str, str]]]:
    term_rules: list[dict[str, object]] = []
    for term in glossary.get("terms", []):
        if not isinstance(term, dict):
            continue
        approved = str(term.get("approved_ar", "")).strip()
        forbidden = [str(item).strip() for item in term.get("forbidden_ar", []) if str(item).strip()]
        if approved or forbidden:
            term_rules.append(
                {
                    "term_en": str(term.get("term_en", "")).strip(),
                    "approved_ar": approved,
                    "forbidden_ar": forbidden,
                }
            )

    global_forbidden: list[tuple[str, str]] = []
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            if not isinstance(item, dict):
                continue
            forbidden = str(item.get("forbidden_ar", "")).strip()
            approved = str(item.get("use_instead", "")).strip()
            if forbidden and approved:
                global_forbidden.append((forbidden, approved))
    return term_rules, global_forbidden


def detect_spacing_issues(key: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    trimmed = text.strip()
    if trimmed != text:
        findings.append(
            make_finding(
                key,
                "whitespace",
                "low",
                "Remove leading or trailing whitespace from this Arabic string.",
                text,
                trimmed,
                fix_mode="auto_safe",
            )
        )

    if REPEATED_SPACE_RE.search(text) and not is_risky_for_whitespace_normalization(text):
        findings.append(
            make_finding(
                key,
                "spacing",
                "low",
                "Normalize repeated internal spaces in this Arabic string.",
                text,
                REPEATED_SPACE_RE.sub(" ", text),
                fix_mode="auto_safe",
            )
        )

    if SPACE_BEFORE_AR_PUNCT_RE.search(text):
        findings.append(
            make_finding(
                key,
                "punctuation_spacing",
                "low",
                "Remove the space before Arabic punctuation for cleaner UI text.",
                text,
                SPACE_BEFORE_AR_PUNCT_RE.sub(r"\1", text),
                fix_mode="auto_safe",
            )
        )

    if SPACE_AFTER_OPENING_BRACKET_RE.search(text) or SPACE_BEFORE_CLOSING_BRACKET_RE.search(text):
        updated = SPACE_AFTER_OPENING_BRACKET_RE.sub(r"\1", text)
        updated = SPACE_BEFORE_CLOSING_BRACKET_RE.sub(r"\1", updated)
        findings.append(
            make_finding(
                key,
                "bracket_spacing",
                "low",
                "Normalize spacing around brackets for cleaner UI formatting.",
                text,
                updated,
                fix_mode="auto_safe",
            )
        )

    slash_match = SLASH_SPACING_RE.search(text)
    if slash_match and " / " in text:
        findings.append(
            make_finding(
                key,
                "slash_spacing",
                "low",
                "Normalize spacing around the slash separator.",
                text,
                SLASH_SPACING_RE.sub("/", text),
                fix_mode="auto_safe",
            )
        )
    return findings


def detect_punctuation_issues(key: str, text: str, toggles: dict[str, bool]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if any((is_likely_technical_text(text), has_html_or_xml(text), has_icu_syntax(text), bool(parse_placeholders(text)))):
        return findings

    replacements = {",": "،", ";": "؛", "?": "؟"}
    english_punct_found = [char for char in replacements if char in text]
    if contains_arabic(text) and english_punct_found:
        updated = text
        replaced_pairs: list[str] = []
        for source, target in replacements.items():
            if source in updated:
                updated = updated.replace(source, target)
                replaced_pairs.append(f"{source}->{target}")
        findings.append(
            make_finding(
                key,
                "english_punctuation",
                "low",
                "Arabic text uses English punctuation. Review whether Arabic punctuation is preferred here.",
                text,
                updated,
                related=", ".join(replaced_pairs),
                fix_mode="auto_safe",
            )
        )

    for english_punct, arabic_punct in MIXED_PUNCTUATION_PAIRS:
        if english_punct in text and arabic_punct in text:
            findings.append(
                make_finding(
                key,
                "mixed_punctuation",
                "medium",
                "This string mixes Arabic and English punctuation. Review punctuation style consistency.",
                text,
                related=f"{english_punct} and {arabic_punct}",
                )
            )
            break

    repeated = REPEATED_PUNCTUATION_RE.search(text)
    if repeated:
        collapsed = REPEATED_PUNCTUATION_RE.sub(r"\1", text)
        findings.append(
            make_finding(
                key,
                "repeated_punctuation",
                "medium",
                "Repeated punctuation looks noisy in UI text. Review tone and punctuation count.",
                text,
                collapsed,
                fix_mode="review_required",
            )
        )

    # This rule was intentionally tightened because flagging every exclamation mark
    # created high noise for otherwise acceptable short celebratory strings.
    stripped = text.strip()
    short_emphatic = (
        "!" in stripped
        and len(stripped) <= 12
        and any(token in stripped for token in SHORT_EXCLAMATION_TRIGGER_TOKENS)
    )
    if toggles.get("enable_exclamation_style", True) and ("!!" in text or short_emphatic):
        findings.append(
            make_finding(
                key,
                "exclamation_style",
                "info",
                "Exclamation marks in Arabic UI text should be used sparingly. Review tone for consistency.",
                text,
            )
        )
    return findings


def detect_terminology_issues(
    key: str,
    en_text: str,
    ar_text: str,
    term_rules: list[dict[str, object]],
    global_forbidden: list[tuple[str, str]],
    context_bundle: dict[str, object],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    for forbidden, approved in global_forbidden:
        if forbidden in ar_text:
            candidate = ar_text.replace(forbidden, approved)
            decision = evaluate_candidate_change(context_bundle, candidate)
            blocked = decision["review_required"]
            findings.append(
                make_finding(
                    key,
                    "context_sensitive_term_conflict" if blocked else "forbidden_term",
                    "medium" if blocked else "high",
                    (
                        f"Arabic text uses forbidden term '{forbidden}', but the replacement is context-sensitive."
                        if blocked
                        else f"Arabic text uses forbidden term '{forbidden}'. Replace it with the approved glossary term."
                    ),
                    ar_text,
                    "" if blocked else candidate,
                    related=f"use {approved}",
                    fix_mode="review_required",
                    context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                    review_reason=str(decision["review_reason"]),
                )
            )

    for rule in term_rules:
        term_en = str(rule.get("term_en", "")).strip()
        approved = str(rule.get("approved_ar", ""))
        forbidden_terms = [str(item) for item in rule.get("forbidden_ar", [])]
        if term_en and term_en.casefold() in en_text.casefold() and approved and approved not in ar_text:
            for forbidden in forbidden_terms:
                if forbidden not in ar_text:
                    continue
                candidate = ar_text.replace(forbidden, approved)
                decision = evaluate_candidate_change(context_bundle, candidate)
                findings.append(
                    make_finding(
                        key,
                        "context_sensitive_term_conflict" if decision["review_required"] else "terminology_inconsistency",
                        "medium",
                        "English and Arabic pair indicates a context-sensitive glossary conflict. Human review required."
                        if decision["review_required"]
                        else "Arabic text uses a non-approved glossary variant.",
                        ar_text,
                        "" if decision["review_required"] else candidate,
                        related=f"{forbidden} vs {approved}",
                        fix_mode="review_required",
                        context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                        review_reason=str(decision["review_reason"]),
                    )
                )
                break
        if approved and approved in ar_text:
            for forbidden in forbidden_terms:
                if forbidden in ar_text:
                    decision = evaluate_candidate_change(context_bundle, ar_text.replace(forbidden, approved))
                    findings.append(
                        make_finding(
                            key,
                            "context_sensitive_term_conflict" if decision["review_required"] else "terminology_inconsistency",
                            "medium",
                            "Arabic text mixes approved and forbidden terminology variants."
                            if not decision["review_required"]
                            else "Arabic text mixes glossary variants in a context-sensitive sentence. Human review required.",
                            ar_text,
                            related=f"{forbidden} vs {approved}",
                            fix_mode="review_required",
                            context_bundle={**context_bundle, "semantic_risk": decision["semantic_risk"], "context_sensitive_term_flags": decision["context_flags"]},
                            review_reason=str(decision["review_reason"]),
                        )
                    )
                    break
    return findings


def detect_mixed_script_issues(key: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not text.strip():
        return findings

    compact_key = re.sub(r"[^A-Za-z0-9]+", "", key).casefold()
    compact_text = re.sub(r"[^A-Za-z0-9]+", "", text).casefold()
    if compact_key and compact_text and compact_key == compact_text:
        return findings

    if URL_OR_EMAIL_RE.search(text):
        sanitized = URL_OR_EMAIL_RE.sub("", text)
    else:
        sanitized = text

    latin_tokens = []
    for token in LATIN_TOKEN_RE.findall(sanitized):
        if token.casefold() in ALLOWED_LATIN_TOKEN_FOLDS:
            continue
        if re.fullmatch(r"[A-Z]{2,4}", token):
            continue
        latin_tokens.append(token)

    if not contains_arabic(text) and latin_tokens:
        findings.append(
            make_finding(
                key,
                "untranslated_english",
                "high",
                "Arabic locale value appears to be untranslated English or Latin text.",
                text,
                fix_mode="review_required",
            )
        )
    elif contains_arabic(text) and latin_tokens:
        findings.append(
            make_finding(
                key,
                "mixed_script",
                "medium",
                "Arabic string contains raw Latin words that may be untranslated.",
                text,
                related=", ".join(sorted(set(latin_tokens))[:8]),
                fix_mode="review_required",
            )
        )
    return findings


def detect_literal_translation_issues(key: str, text: str, context_bundle: dict[str, object]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not contains_arabic(text):
        return findings
    # Literal-translation hints are restricted to a short controlled list because
    # broader phrasing heuristics produced too many stylistic false positives.
    normalized = normalize_for_compare(text)
    for item in LITERAL_PATTERNS:
        phrase = str(item["text"])
        if phrase not in normalized:
            continue
        if not any(context in normalized for context in item["contexts"]):
            continue
        findings.append(
            make_finding(
                key,
                "suspicious_literal_translation",
                "info",
                str(item["message"]),
                text,
                fix_mode="review_required",
                context_bundle=context_bundle,
            )
        )
    return findings


def detect_empty_or_weak_issues(key: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    stripped = text.strip()
    if not stripped:
        findings.append(
            make_finding(
                key,
                "empty_string",
                "high",
                "Arabic locale value is empty and should be completed.",
                text,
                fix_mode="review_required",
            )
        )
        return findings

    if PLACEHOLDER_TEXT_RE.fullmatch(stripped):
        findings.append(
            make_finding(
                key,
                "placeholder_text",
                "high",
                "Arabic locale value looks like placeholder text or an unfinished translation.",
                text,
                fix_mode="review_required",
            )
        )
    elif WEAK_ONLY_PUNCT_RE.fullmatch(stripped):
        findings.append(
            make_finding(
                key,
                "weak_text",
                "medium",
                "Arabic locale value contains only punctuation or non-word symbols. Review whether text is missing.",
                text,
                fix_mode="review_required",
            )
        )
    return findings


def detect_style_issues(key: str, text: str, toggles: dict[str, bool]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    stripped = text.strip()
    if not stripped or not toggles.get("enable_long_ui_string", True):
        return findings
    if len(stripped) > 120:
        findings.append(
            make_finding(
                key,
                "long_ui_string",
                "info",
                "Arabic UI text is long. Review layout fit and readability in the actual screen context.",
                text,
                related=f"{len(stripped)} chars",
            )
        )
    return findings


def dedupe_findings(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        signature = (row["key"], row["issue_type"], row["message"], row["old"], row["new"])
        if signature not in seen:
            seen.add(signature)
            deduped.append(row)
    return deduped


def detect_duplicate_and_inconsistency_issues(
    en_data: dict[str, object],
    ar_data: dict[str, object],
    toggles: dict[str, bool],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    english_to_arabic: defaultdict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for key, en_value in en_data.items():
        ar_value = ar_data.get(key)
        if not isinstance(en_value, str) or not isinstance(ar_value, str):
            continue
        en_norm = normalize_for_compare(en_value.casefold())
        ar_norm = normalize_for_compare(ar_value)
        if en_norm and ar_norm:
            english_to_arabic[en_norm][ar_norm].append(key)

    for _en_norm, translations in english_to_arabic.items():
        if len(translations) <= 1:
            continue
        grouped = sorted(translations.items(), key=lambda item: (-len(item[1]), item[0]))
        canonical, canonical_keys = grouped[0]
        canonical_soft = strip_punctuation_for_compare(canonical)
        for translation, keys in grouped[1:]:
            translation_soft = strip_punctuation_for_compare(translation)
            if translation_soft != canonical_soft:
                findings.append(
                    make_finding(
                        keys[0],
                        "inconsistent_translation",
                        "medium",
                        "The same English source text appears with different Arabic translations. Review which wording should be standard.",
                        translation,
                        canonical,
                        related=", ".join(sorted(set(canonical_keys + keys))),
                        fix_mode="review_required",
                    )
                )
            elif toggles.get("enable_similar_phrase_variation", True) and translation != canonical:
                # This rule is intentionally limited to punctuation and formatting-only
                # variation within the same English source group to avoid semantic noise.
                findings.append(
                    make_finding(
                        keys[0],
                        "similar_phrase_variation",
                        "info",
                        "The same English source text differs only by Arabic punctuation or formatting. Consider standardizing the display style.",
                        translation,
                        canonical,
                        related=", ".join(sorted(set(canonical_keys + keys))),
                        fix_mode="review_required",
                    )
                )
    return findings


def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(runtime.ar_file))
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--glossary", default=str(runtime.glossary_file))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "ar_locale_qc" / "ar_locale_qc_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / "per_tool" / "ar_locale_qc" / "ar_locale_qc_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / "per_tool" / "ar_locale_qc" / "ar_locale_qc_report.xlsx"))
    args = parser.parse_args()

    ar_data = load_locale_mapping(Path(args.input), runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    en_data = load_locale_mapping(Path(args.en), runtime, runtime.source_locale)
    glossary = load_json_dict(Path(args.glossary))
    rule_toggles = load_rule_toggles(runtime.config_dir / "config.json")
    term_rules, global_forbidden = load_glossary_rules(glossary)
    usage_data = scan_code_usage(
        runtime.code_dirs,
        runtime.usage_patterns,
        runtime.allowed_extensions,
        profile=runtime.project_profile,
        locale_format=runtime.locale_format,
        locale_keys=set(en_data) | set(ar_data),
    )
    usage_contexts = usage_data.get("usage_contexts", {})
    lt_signals = merge_linguistic_signals(
        load_en_languagetool_signals(runtime.results_dir),
        build_language_tool_python_signals(ar_data, runtime),
    )

    rows: list[dict[str, str]] = []

    for key, value in ar_data.items():
        if not isinstance(value, str):
            continue
        text = value
        en_text = str(en_data.get(key, ""))
        context_bundle = build_context_bundle(
            key,
            en_text,
            text,
            usage_locations=list(usage_contexts.get(key, [])),
            linguistic_signals=lt_signals.get(key),
        )
        rows.extend(detect_empty_or_weak_issues(key, text))
        rows.extend(detect_spacing_issues(key, text))
        rows.extend(detect_punctuation_issues(key, text, rule_toggles))
        rows.extend(detect_terminology_issues(key, en_text, text, term_rules, global_forbidden, context_bundle))
        rows.extend(detect_mixed_script_issues(key, text))
        if rule_toggles.get("enable_suspicious_literal_translation", True):
            rows.extend(detect_literal_translation_issues(key, text, context_bundle))
        rows.extend(detect_style_issues(key, text, rule_toggles))

    rows.extend(detect_duplicate_and_inconsistency_issues(en_data, ar_data, rule_toggles))

    rows = dedupe_findings(rows)
    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"], item["old"]))

    issue_counts = Counter(row["issue_type"] for row in rows)
    payload = {
        "input_file": str(Path(args.input).resolve()),
        "en_file": str(Path(args.en).resolve()),
        "glossary_file": str(Path(args.glossary).resolve()),
        "summary": {
            "keys_scanned": len(ar_data),
            "findings": len(rows),
            "issue_types": dict(sorted(issue_counts.items())),
        },
        "findings": rows,
    }

    fieldnames = [
        "key",
        "issue_type",
        "severity",
        "message",
        "old",
        "new",
        "related",
        "audit_source",
        "fix_mode",
        "context_type",
        "context_flags",
        "semantic_risk",
        "lt_signals",
        "review_reason",
    ]
    write_json(payload, Path(args.out_json))
    write_csv(rows, fieldnames, Path(args.out_csv))
    write_simple_xlsx(rows, fieldnames, Path(args.out_xlsx), sheet_name="AR Locale QC")
    print(f"Done. Arabic locale QC issues found: {len(rows)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()
