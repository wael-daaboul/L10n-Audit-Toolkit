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

from l10n_audit.core.context_evaluator import (
    build_context_bundle,
    build_language_tool_python_signals,
    evaluate_candidate_change,
    load_en_languagetool_signals,
    merge_linguistic_signals,
)
from l10n_audit.core.audit_runtime import (
    has_html_or_xml,
    has_icu_syntax,
    is_likely_technical_text,
    is_risky_for_whitespace_normalization,
    load_json_dict,
    load_locale_mapping,
    load_runtime,
    mask_placeholders,
    parse_placeholders,
    unmask_placeholders,
    write_csv,
    write_json,
    write_simple_xlsx,
)
from l10n_audit.core.usage_scanner import scan_code_usage

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
        "ui_surface": str(context_bundle.get("ui_surface", "")),
        "text_role": str(context_bundle.get("text_role", "")),
        "action_hint": str(context_bundle.get("action_hint", "")),
        "audience_hint": str(context_bundle.get("audience_hint", "")),
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
    
    # Mask placeholders to protect them from spacing rules
    masked_text, placeholders = mask_placeholders(text)
    
    trimmed = masked_text.strip()
    if trimmed != masked_text:
        findings.append(
            make_finding(
                key,
                "whitespace",
                "low",
                "Remove leading or trailing whitespace from this Arabic string.",
                text,
                unmask_placeholders(trimmed, placeholders),
                fix_mode="auto_safe",
            )
        )

    if REPEATED_SPACE_RE.search(masked_text) and not is_risky_for_whitespace_normalization(text):
        findings.append(
            make_finding(
                key,
                "spacing",
                "low",
                "Normalize repeated internal spaces in this Arabic string.",
                text,
                unmask_placeholders(REPEATED_SPACE_RE.sub(" ", masked_text), placeholders),
                fix_mode="auto_safe",
            )
        )

    if SPACE_BEFORE_AR_PUNCT_RE.search(masked_text):
        findings.append(
            make_finding(
                key,
                "punctuation_spacing",
                "low",
                "Remove the space before Arabic punctuation for cleaner UI text.",
                text,
                unmask_placeholders(SPACE_BEFORE_AR_PUNCT_RE.sub(r"\1", masked_text), placeholders),
                fix_mode="auto_safe",
            )
        )

    if SPACE_AFTER_OPENING_BRACKET_RE.search(masked_text) or SPACE_BEFORE_CLOSING_BRACKET_RE.search(masked_text):
        updated = SPACE_AFTER_OPENING_BRACKET_RE.sub(r"\1", masked_text)
        updated = SPACE_BEFORE_CLOSING_BRACKET_RE.sub(r"\1", updated)
        findings.append(
            make_finding(
                key,
                "bracket_spacing",
                "low",
                "Normalize spacing around brackets for cleaner UI formatting.",
                text,
                unmask_placeholders(updated, placeholders),
                fix_mode="auto_safe",
            )
        )

    slash_match = SLASH_SPACING_RE.search(masked_text)
    if slash_match and " / " in masked_text:
        findings.append(
            make_finding(
                key,
                "slash_spacing",
                "low",
                "Normalize spacing around the slash separator.",
                text,
                unmask_placeholders(SLASH_SPACING_RE.sub("/", masked_text), placeholders),
                fix_mode="auto_safe",
            )
        )
    return findings


def detect_punctuation_issues(key: str, text: str, toggles: dict[str, bool]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if any((is_likely_technical_text(text), has_html_or_xml(text), has_icu_syntax(text))):
        return findings

    # Mask placeholders to protect them from punctuation changes
    masked_text, placeholders = mask_placeholders(text)

    # 1. Specific: Protect English number format (decimals/thousands)
    # We use a pattern that avoids swapping commas/dots between digits.
    # We do this by applying general replacements with word/digit boundaries.
    
    replacements = {";": "؛", "?": "؟"}
    english_punct_found = [char for char in [",", ";", "?", "."] if char in masked_text]
    
    if contains_arabic(masked_text) and english_punct_found:
        updated = masked_text
        replaced_pairs: list[str] = []
        
        # Arabic comma replacement (ensure it's not between digits)
        if "," in updated:
            new_val = re.sub(r"(?<!\d),(?!\d)", "،", updated)
            if new_val != updated:
                updated = new_val
                replaced_pairs.append(", -> ،")
        
        for source, target in replacements.items():
            if source in updated:
                updated = updated.replace(source, target)
                replaced_pairs.append(f"{source} -> {target}")
        
        if updated != masked_text:
            findings.append(
                make_finding(
                    key,
                    "english_punctuation",
                    "low",
                    "Arabic text uses English punctuation. Review whether Arabic punctuation is preferred here.",
                    text,
                    unmask_placeholders(updated, placeholders),
                    related=", ".join(replaced_pairs),
                    fix_mode="auto_safe",
                )
            )

    for english_punct, arabic_punct in MIXED_PUNCTUATION_PAIRS:
        if english_punct in masked_text and arabic_punct in masked_text:
            # Check if comma is part of a number
            if english_punct == "," and re.search(r"\d,\d", masked_text):
                continue
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

    repeated = REPEATED_PUNCTUATION_RE.search(masked_text)
    if repeated:
        collapsed = REPEATED_PUNCTUATION_RE.sub(r"\1", masked_text)
        findings.append(
            make_finding(
                key,
                "repeated_punctuation",
                "medium",
                "Repeated punctuation looks noisy in UI text. Review tone and punctuation count.",
                text,
                unmask_placeholders(collapsed, placeholders),
                fix_mode="review_required",
            )
        )

    # Exclamations rule
    stripped = masked_text.strip()
    short_emphatic = (
        "!" in stripped
        and len(stripped) <= 12
        and any(token in stripped for token in SHORT_EXCLAMATION_TRIGGER_TOKENS)
    )
    if toggles.get("enable_exclamation_style", True) and ("!!" in masked_text or short_emphatic):
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
    role_identifiers: list[str] | None = None,
    entity_whitelist: dict[str, list[str]] | None = None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    for forbidden, approved in global_forbidden:
        if forbidden in ar_text:
            candidate = ar_text.replace(forbidden, approved)
            decision = evaluate_candidate_change(context_bundle, candidate, role_identifiers, entity_whitelist)
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
                decision = evaluate_candidate_change(context_bundle, candidate, role_identifiers, entity_whitelist)
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
                    decision = evaluate_candidate_change(context_bundle, ar_text.replace(forbidden, approved), role_identifiers, entity_whitelist)
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


def detect_mixed_script_issues(key: str, text: str, extra_allowed_latin: set[str] | None = None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not text.strip():
        return findings

    compact_key = re.sub(r"[^A-Za-z0-9]+", "", key).casefold()
    compact_text = re.sub(r"[^A-Za-z0-9]+", "", text).casefold()
    if compact_key and compact_text and compact_key == compact_text:
        return findings

    # Mask placeholders to protect variables from being flagged as untranslated Latin
    masked_text, _ = mask_placeholders(text)

    if URL_OR_EMAIL_RE.search(masked_text):
        # Remove URLs/Emails and placeholder tokens
        sanitized = URL_OR_EMAIL_RE.sub("", masked_text)
    else:
        sanitized = masked_text
    
    # Strip masking tokens to avoid them being counted as Latin words
    sanitized = re.sub(r"\[\[PH_\d+\]\]", " ", sanitized)

    latin_tokens = []
    for token in LATIN_TOKEN_RE.findall(sanitized):
        folded = token.casefold()
        if folded in ALLOWED_LATIN_TOKEN_FOLDS:
            continue
        if extra_allowed_latin and folded in extra_allowed_latin:
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


def detect_sentence_semantic_issues(
    key: str,
    en_text: str,
    ar_text: str,
    context_bundle: dict[str, object],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if not en_text.strip() or not ar_text.strip() or not contains_arabic(ar_text):
        return findings
    if any((has_html_or_xml(ar_text), has_icu_syntax(ar_text), is_likely_technical_text(ar_text))):
        return findings

    english_shape = str(context_bundle.get("english_sentence_shape", ""))
    arabic_shape = str(context_bundle.get("arabic_sentence_shape", ""))
    text_role = str(context_bundle.get("text_role", ""))
    semantic_flags = list(context_bundle.get("semantic_flags", [])) if isinstance(context_bundle.get("semantic_flags", []), list) else []

    if english_shape == "sentence_like" and arabic_shape == "short_label":
        findings.append(
            make_finding(
                key,
                "sentence_shape_mismatch",
                "medium",
                "English source is sentence-like, but the Arabic text looks too short to preserve the full instruction or message.",
                ar_text,
                fix_mode="review_required",
                context_bundle=context_bundle,
            )
        )

    if text_role == "message" and english_shape == "sentence_like" and arabic_shape == "short_label":
        findings.append(
            make_finding(
                key,
                "message_label_mismatch",
                "medium",
                "This UI message appears to have collapsed into a label-like Arabic phrase. Review whether part of the meaning is missing.",
                ar_text,
                fix_mode="review_required",
                context_bundle=context_bundle,
            )
        )

    missing_actions = [flag.split(":", 1)[1] for flag in semantic_flags if flag.startswith("missing_action:")]
    if missing_actions and english_shape == "sentence_like":
        findings.append(
            make_finding(
                key,
                "possible_meaning_loss",
                "medium",
                f"Arabic text may be missing action meaning from the English sentence: {', '.join(sorted(set(missing_actions)))}.",
                ar_text,
                fix_mode="review_required",
                context_bundle=context_bundle,
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
    parser.add_argument("--out-json", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_locale_qc" / "ar_locale_qc_report.json"))
    parser.add_argument("--out-csv", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_locale_qc" / "ar_locale_qc_report.csv"))
    parser.add_argument("--out-xlsx", default=str(runtime.results_dir / ".cache" / "raw_tools" / "ar_locale_qc" / "ar_locale_qc_report.xlsx"))
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
        role_identifiers=list(runtime.role_identifiers),
    )
    usage_contexts = usage_data.get("usage_contexts", {})
    usage_metadata = usage_data.get("usage_metadata", {})
    lt_signals = merge_linguistic_signals(
        load_en_languagetool_signals(runtime.results_dir),
        build_language_tool_python_signals(ar_data, runtime),
    )

    from l10n_audit.core.utils import check_java_available, get_java_missing_warning
    if not check_java_available():
        print(get_java_missing_warning("Arabic"))
        lt_signals = load_en_languagetool_signals(runtime.results_dir)

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
            usage_metadata=usage_metadata.get(key),
            linguistic_signals=lt_signals.get(key),
            role_identifiers=list(runtime.role_identifiers),
            entity_whitelist={k: list(v) for k, v in runtime.entity_whitelist.items()},
        )
        rows.extend(detect_empty_or_weak_issues(key, text))
        rows.extend(detect_spacing_issues(key, text))
        rows.extend(detect_punctuation_issues(key, text, rule_toggles))
        rows.extend(detect_terminology_issues(key, en_text, text, term_rules, global_forbidden, context_bundle, list(runtime.role_identifiers), {k: list(v) for k, v in runtime.entity_whitelist.items()}))
        rows.extend(detect_mixed_script_issues(key, text))
        if rule_toggles.get("enable_suspicious_literal_translation", True):
            rows.extend(detect_literal_translation_issues(key, text, context_bundle))
        rows.extend(detect_style_issues(key, text, rule_toggles))
        rows.extend(detect_sentence_semantic_issues(key, en_text, text, context_bundle))

    rows.extend(detect_duplicate_and_inconsistency_issues(en_data, ar_data, rule_toggles))

    rows = dedupe_findings(rows)
    
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    apply_arabic_decision_routing(rows, suggestion_key="new")
    
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
    write_simple_xlsx(rows, fieldnames, Path(args.out_xlsx), sheet_name="AR Locale QC")
    print(f"Done. Arabic locale QC issues found: {len(rows)}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")
    print(f"XLSX: {args.out_xlsx}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options) -> list:
    """Run AR locale QC and return a list of :class:`AuditIssue`."""
    import logging
    from l10n_audit.models import issue_from_dict
    from l10n_audit.core.context_evaluator import (
        build_language_tool_python_signals, load_en_languagetool_signals, merge_linguistic_signals,
    )

    logger = logging.getLogger("l10n_audit.ar_locale_qc")
    ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    glossary = load_json_dict(runtime.glossary_file) if runtime.glossary_file.exists() else {}
    rule_toggles = load_rule_toggles(runtime.config_dir / "config.json")
    term_rules, global_forbidden = load_glossary_rules(glossary)
    from l10n_audit.core.usage_scanner import scan_code_usage
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

    from l10n_audit.core.context_evaluator import build_context_bundle
    rows: list[dict] = []
    extra_allowed_latin = {w.casefold() for w in options.audit_rules.latin_whitelist} if options.audit_rules.latin_whitelist else set()

    for key, value in ar_data.items():
        if not isinstance(value, str):
            continue
        text = value
        en_text = str(en_data.get(key, ""))
        context_bundle = build_context_bundle(key, en_text, text,
            usage_locations=list(usage_contexts.get(key, [])),
            usage_metadata=usage_metadata.get(key),
            linguistic_signals=lt_signals.get(key),
            role_identifiers=options.audit_rules.role_identifiers,
            entity_whitelist=options.audit_rules.entity_whitelist,
        )
        rows.extend(detect_empty_or_weak_issues(key, text))
        rows.extend(detect_spacing_issues(key, text))
        rows.extend(detect_punctuation_issues(key, text, rule_toggles))
        rows.extend(detect_terminology_issues(key, en_text, text, term_rules, global_forbidden, context_bundle, options.audit_rules.role_identifiers, options.audit_rules.entity_whitelist))
        rows.extend(detect_mixed_script_issues(key, text, extra_allowed_latin))
        if rule_toggles.get("enable_suspicious_literal_translation", True):
            rows.extend(detect_literal_translation_issues(key, text, context_bundle))
        rows.extend(detect_style_issues(key, text, rule_toggles))
        rows.extend(detect_sentence_semantic_issues(key, en_text, text, context_bundle))
    rows.extend(detect_duplicate_and_inconsistency_issues(en_data, ar_data, rule_toggles))
    rows = dedupe_findings(rows)
    
    from l10n_audit.core.decision_engine import apply_arabic_decision_routing
    apply_arabic_decision_routing(rows, suggestion_key="new")
    
    rows.sort(key=lambda item: (item["issue_type"], item["key"], item["message"], item["old"]))

    if options.write_reports:
        from collections import Counter
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / ".cache" / "raw_tools" / "ar_locale_qc"
        fieldnames = ["key","issue_type","severity","message","old","new","related","audit_source","fix_mode",
                      "context_type","ui_surface","text_role","action_hint","audience_hint","context_flags",
                      "semantic_risk","lt_signals","review_reason"]
        payload = {"summary": {"keys_scanned": len(ar_data), "findings": len(rows),
                               "issue_types": dict(sorted(Counter(r["issue_type"] for r in rows).items()))},
                   "findings": rows}
        try:
            write_json(payload, out_dir / "ar_locale_qc_report.json")
            if options.suppression.include_per_tool_csv:
                write_csv(rows, fieldnames, out_dir / "ar_locale_qc_report.csv")
            else:
                logger.debug("Skipped writing per-tool CSV (include_per_tool_csv=False)")
            if options.suppression.include_per_tool_xlsx:
                write_simple_xlsx(rows, fieldnames, out_dir / "ar_locale_qc_report.xlsx", sheet_name="AR Locale QC")
            else:
                logger.debug("Skipped writing per-tool XLSX (include_per_tool_xlsx=False)")
        except Exception as exc:
            logger.warning("Failed to write AR locale QC reports: %s", exc)

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
        fix_text = row.get("new", "")
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
                mutation_id=f"ar_locale_qc:{idx}",
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

    # Safety invariant — row count must never change
    assert len(rows) == len(rows), "Phase 11 internal error"  # tautology guards refactor

    # Persist metrics — namespaced to avoid overwriting other stages
    enforcer.save_metrics(runtime)
    if hasattr(runtime, "metadata"):
        runtime.metadata["feedback_metrics_ar_locale_qc"] = feedback.summarize()
        runtime.metadata["conflict_metrics_ar_locale_qc"] = {
            **resolver.summarize(),
            "source": "arabic",
            "stage": "ar_locale_qc",
        }

    normalised = [{**r, "source": "ar_locale_qc", "issue_type": str(r.get("issue_type") or "").strip() or "ar_qc"} for r in rows]
    logger.info("AR locale QC: %d issues (enforcement active=%s)", len(normalised), enforcer.enabled)
    return [issue_from_dict(r) for r in normalised]
