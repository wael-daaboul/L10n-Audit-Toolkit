from __future__ import annotations

import re
import logging
from typing import Any

from l10n_audit.core.ai_trace import (
    emit_ai_decision_trace,
    emit_ai_fallback,
    get_metrics,
    is_ai_debug_mode,
)

# ---------------------------------------------------------------------------
# Phase 5: Deterministic Semantic Acceptance Gate
# ---------------------------------------------------------------------------
# These are Arabic domain-specific concepts that should trigger rejection if
# they appear in the candidate but are absent from source text and context.
# Words are listed as root substrings to handle Arabic morphological variation.
_INJECTED_CONCEPT_ROOTS: tuple[str, ...] = (
    "ذروة",   # peak (e.g. rush hour)
    "ازدحام", # congestion / traffic jam
    "ازحام",  # variant of congestion
    "رهاب",   # phobia (unexpected domain shift)
    "ذعر",    # panic
)

# English words whose presence in the SOURCE signals polarity-negative intent.
# We check for these and then confirm the candidate preserves the negation.
_NEGATION_WORDS_EN: tuple[str, ...] = (
    "not ", "don't", "do not", "cannot", "can't", "never",
    "no ", "without", "disable", "stop ", "cancel",
)

# Arabic negation markers — candidate must contain at least one if source is negative.
_NEGATION_MARKERS_AR: tuple[str, ...] = (
    "لا ", "لن ", "لم ", "لست", "ليس", "بدون", "غير ", "عدم",
    "إيقاف", "إلغاء", "توقف",
)

# Action verbs whose absence in the candidate signals intent loss.
# Keyed on (casefold) English action -> tuple of acceptable Arabic equivalents.
_ACTION_MAP: dict[str, tuple[str, ...]] = {
    "pick":   ("اختر", "حدد", "اختيار", "تحديد"),
    "select": ("اختر", "حدد", "اختيار", "تحديد"),
    "choose": ("اختر", "حدد", "اختيار", "تحديد"),
    "add":    ("أضف", "إضافة", "أضاف"),
    "save":   ("احفظ", "حفظ"),
    "send":   ("أرسل", "إرسال"),
    "delete": ("احذف", "حذف"),
    "approve":("وافق", "موافقة"),
    "enter":  ("أدخل", "إدخال"),
    "set":    ("حدد", "ضبط", "اضبط"),
    "confirm":("تأكيد", "أكّد", "أكد"),
    # "cancel" conjugation variants: إلغاء (noun), ألغِ (imperative 2m), تلغِ/يلغِ (jussive)
    "cancel": ("إلغاء", "ألغ", "تلغ", "يلغ"),
    "open":   ("افتح", "فتح"),
    "close":  ("أغلق", "إغلاق"),
}

# Core English concept words that MUST map to some presence in the candidate.
# If the source contains the key and the candidate has no coverage, flag it.
_CORE_CONCEPT_PRESENCE: dict[str, tuple[str, ...]] = {
    "time":    ("وقت", "ساعة", "تاريخ", "موعد"),
    "date":    ("تاريخ", "يوم"),
    "name":    ("اسم", "الاسم"),
    "email":   ("بريد", "ايميل", "إيميل"),
    "phone":   ("هاتف", "جوال", "موبايل", "رقم"),
    "password":("كلمة مرور", "كلمة السر"),
    "location":("موقع", "عنوان"),
    "address": ("عنوان",),
    "amount":  ("مبلغ", "قيمة", "كمية"),
    "number":  ("رقم", "عدد"),
    # "message" singular + "رسائل" plural
    "message": ("رسالة", "رسائل"),
    "file":    ("ملف",),
    "image":   ("صورة",),
    "account": ("حساب",),
    "payment": ("دفع", "سداد", "مدفوع"),
    "order":   ("طلب",),
    "status":  ("حالة",),
}


def _word_tokens(text: str) -> list[str]:
    """Return lowercase word tokens from any mixed-language text."""
    return re.findall(r"[A-Za-z\u0600-\u06FF]+", text.casefold())


def _source_token_count(source_text: str) -> int:
    """Count meaningful word tokens in the source (for short-string mode)."""
    return len(re.findall(r"\S+", source_text.strip()))


def _check_concept_injection(
    source_text: str,
    candidate_text: str,
    context: str | None,
) -> list[str]:
    """Return reason codes for Arabic concepts that appear in candidate but
    are not supported by source text or context.

    This is the key check for the canonical rejection case:
      source: 'Pick time for now'
      bad AI: 'وقت الذروة الآن'  ← 'ذروة' (peak) was injected
    """
    codes: list[str] = []
    combined_source = (source_text + " " + (context or "")).casefold()
    for root in _INJECTED_CONCEPT_ROOTS:
        if root in candidate_text and root not in combined_source:
            codes.append("semantic_concept_injection")
            break
    return codes


def _check_key_concept_coverage(
    source_text: str,
    candidate_text: str,
    placeholders: list[str] | None,
) -> list[str]:
    """Return reason codes when important source concepts are absent from candidate."""
    codes: list[str] = []
    source_lower = source_text.casefold()

    # Check action intent coverage
    for action_en, arabic_forms in _ACTION_MAP.items():
        if action_en in source_lower:
            if not any(ar in candidate_text for ar in arabic_forms):
                codes.append("semantic_key_concept_loss")
                break  # one code is enough per check

    # Check important concept words
    for concept_en, arabic_forms in _CORE_CONCEPT_PRESENCE.items():
        if concept_en in source_lower:
            if not any(ar in candidate_text for ar in arabic_forms):
                # Only flag if the placeholder doesn't cover it
                covered_by_placeholder = any(
                    concept_en in (ph.strip("{}:% ").lower()) for ph in (placeholders or [])
                )
                if not covered_by_placeholder:
                    codes.append("semantic_key_concept_loss")
                    break

    return codes


def _check_polarity(source_text: str, candidate_text: str) -> list[str]:
    """Detect negation/polarity flips between source and candidate."""
    codes: list[str] = []
    source_lower = source_text.casefold()
    source_is_negative = any(neg in source_lower for neg in _NEGATION_WORDS_EN)
    if source_is_negative:
        candidate_is_negative = any(neg in candidate_text for neg in _NEGATION_MARKERS_AR)
        if not candidate_is_negative:
            codes.append("semantic_polarity_mismatch")
    return codes


def _check_numbers(source_text: str, candidate_text: str) -> list[str]:
    """Detect when numbers present in source disappear or change in candidate."""
    codes: list[str] = []
    source_nums = set(re.findall(r"\d+", source_text))
    candidate_nums = set(re.findall(r"\d+", candidate_text))
    if source_nums and not source_nums.issubset(candidate_nums):
        codes.append("semantic_number_mismatch")
    return codes


def _check_named_entities(
    source_text: str,
    candidate_text: str,
    glossary: dict[str, Any] | None,
) -> list[str]:
    """Detect when named entities from glossary disappear or mutate in candidate."""
    codes: list[str] = []
    if not glossary:
        return codes
    source_lower = source_text.casefold()
    for item in glossary.get("terms", []) if isinstance(glossary, dict) else []:
        if not isinstance(item, dict):
            continue
        term_en = str(item.get("term_en", "")).strip().casefold()
        approved_ar = str(item.get("approved_ar", "")).strip()
        if not term_en or not approved_ar:
            continue
        if term_en in source_lower:
            # The source mentions this entity; confirm approved_ar is in candidate.
            if approved_ar not in candidate_text:
                codes.append("semantic_named_entity_mismatch")
                break
    return codes


def _check_short_string_strict(
    source_text: str,
    candidate_text: str,
    context: str | None,
    glossary: dict[str, Any] | None,
) -> list[str]:
    """Apply stricter rules for short source strings (≤ 4 tokens).

    Short strings must not undergo semantic expansion or domain-specific
    interpretation unless strongly supported by context or glossary.
    """
    codes: list[str] = []
    if _source_token_count(source_text) > 4:
        return codes

    # Concept injection in short strings is a hard reject signal.
    injection_codes = _check_concept_injection(source_text, candidate_text, context)
    if injection_codes:
        # Already captured at outer level; mark as short_text_expansion too.
        codes.append("semantic_short_text_expansion")
        return codes

    # Candidate must not be substantially longer than source suggests.
    candidate_token_count = _source_token_count(candidate_text)
    # Short sources (≤4 tokens) should not balloon beyond 3× in token count;
    # 3× is chosen to allow reasonable articles/prepositions while blocking
    # domain-specific rewrites (e.g. 1-token source → 6+ token output).
    if candidate_token_count > _source_token_count(source_text) * 3:
        has_context_support = bool(context and context.strip())
        has_glossary_support = bool(glossary)
        if not has_context_support and not has_glossary_support:
            codes.append("semantic_short_text_expansion")

    return codes


def evaluate_semantic_acceptance(
    source_text: str,
    candidate_text: str,
    *,
    key: str = "",
    context: str | None = None,
    glossary: dict[str, Any] | None = None,
    placeholders: list[str] | None = None,
) -> dict[str, Any]:
    """Deterministic semantic acceptance gate for AI-generated translations.

    Runs AFTER structural verification (placeholders/newlines/HTML/glossary).
    Does NOT use AI, embeddings, or probabilistic scoring.

    Returns a dict with:
      status       : "accept" | "suspicious" | "reject"
      reason_codes : list of deterministic reason code strings
      details      : dict with per-check sub-results for tracing
    """
    if not source_text or not candidate_text:
        return {"status": "accept", "reason_codes": [], "details": {"skipped": "empty input"}}

    reason_codes: list[str] = []
    details: dict[str, Any] = {}

    # --- Check 1: concept injection ---
    injection_codes = _check_concept_injection(source_text, candidate_text, context)
    reason_codes.extend(injection_codes)
    details["concept_injection"] = injection_codes

    # --- Check 2: key concept coverage ---
    coverage_codes = _check_key_concept_coverage(source_text, candidate_text, placeholders)
    reason_codes.extend(coverage_codes)
    details["key_concept_coverage"] = coverage_codes

    # --- Check 3: polarity / negation parity ---
    polarity_codes = _check_polarity(source_text, candidate_text)
    reason_codes.extend(polarity_codes)
    details["polarity"] = polarity_codes

    # --- Check 4: number parity ---
    number_codes = _check_numbers(source_text, candidate_text)
    reason_codes.extend(number_codes)
    details["numbers"] = number_codes

    # --- Check 5: named entity parity (glossary-driven) ---
    entity_codes = _check_named_entities(source_text, candidate_text, glossary)
    reason_codes.extend(entity_codes)
    details["named_entities"] = entity_codes

    # --- Check 6: short-string strict mode ---
    short_codes = _check_short_string_strict(source_text, candidate_text, context, glossary)
    reason_codes.extend(short_codes)
    details["short_string"] = short_codes

    # De-duplicate while preserving first-occurrence order.
    seen: set[str] = set()
    unique_codes: list[str] = []
    for code in reason_codes:
        if code not in seen:
            seen.add(code)
            unique_codes.append(code)

    # --- Decision model ---
    # Hard-reject codes: any of these → reject
    _REJECT_CODES = frozenset({
        "semantic_concept_injection",
        "semantic_polarity_mismatch",
        "semantic_number_mismatch",
        "semantic_named_entity_mismatch",
        "semantic_short_text_expansion",
    })
    # Soft codes: alone → suspicious
    _SUSPICIOUS_CODES = frozenset({
        "semantic_key_concept_loss",
        "semantic_intent_shift",
    })

    if unique_codes:
        if any(code in _REJECT_CODES for code in unique_codes):
            status = "reject"
        else:
            status = "suspicious"
    else:
        status = "accept"

    if unique_codes:
        logging.debug(
            "Semantic gate [key=%s]: %s — codes=%s", key, status, unique_codes
        )

    return {"status": status, "reason_codes": unique_codes, "details": details}


def decide_ai_outcome(
    semantic_status: str,
    *,
    has_existing_translation: bool,
) -> dict[str, bool | str]:
    """Deterministically map semantic gate output to execution behavior.

    has_existing_translation explicitly captures invocation context
    (repair vs. missing-translation flow) even when both paths currently
    share the same deterministic mapping.
    """
    normalized_status = str(semantic_status or "").strip().lower()
    mapping: dict[tuple[str, bool], dict[str, bool | str]] = {
        ("accept", True): {"decision": "safe", "allow_apply": True, "needs_review": False},
        ("accept", False): {"decision": "safe", "allow_apply": True, "needs_review": False},
        ("suspicious", True): {"decision": "review", "allow_apply": False, "needs_review": True},
        ("suspicious", False): {"decision": "review", "allow_apply": False, "needs_review": True},
        ("reject", True): {"decision": "reject", "allow_apply": False, "needs_review": True},
        ("reject", False): {"decision": "reject", "allow_apply": False, "needs_review": True},
    }
    return mapping.get(
        (normalized_status, bool(has_existing_translation)),
        {"decision": "reject", "allow_apply": False, "needs_review": True},
    )


def check_placeholders(source, suggestion):
    """
    Checks if all placeholders in the source are present in the suggestion.
    Supports: {name}, %s, %(count)d, etc.
    """
    # Simple brackets: {name}
    source_placeholders = set(re.findall(r"\{[^}]+\}", source))
    suggest_placeholders = set(re.findall(r"\{[^}]+\}", suggestion))
    
    # Colon-prefixed: :totalAmount, :collectCash
    source_colons = set(re.findall(r"(?<!\w):[A-Za-z0-9_]+", source))
    suggest_colons = set(re.findall(r"(?<!\w):[A-Za-z0-9_]+", suggestion))
    
    if not source_placeholders.issubset(suggest_placeholders):
        missing = source_placeholders - suggest_placeholders
        return False, f"Missing placeholders (braces): {', '.join(missing)}"
    
    if not source_colons.issubset(suggest_colons):
        missing = source_colons - suggest_colons
        return False, f"Missing placeholders (colon): {', '.join(missing)}"
    
    # Classic printf style: %s, %d, %(count)s
    printf_regex = r"%(\([^)]+\))?[-#0 +]*[\d\.]*[hlL]*[diouxXeEfFgGcrs%]"
    source_printf = set(m.group(0) for m in re.finditer(printf_regex, source))
    suggest_printf = set(m.group(0) for m in re.finditer(printf_regex, suggestion))
    
    if not source_printf.issubset(suggest_printf):
        missing = source_printf - suggest_printf
        return False, f"Printf-style placeholders mismatch: missing {', '.join(missing)}"
    
    return True, ""

def check_newlines(source, suggestion):
    """
    Checks if basic newline occurrences are drastically different.
    We don't want the AI to merge lines if layout depends on them.
    """
    source_newlines = source.count("\n") + source.count("\\n")
    suggest_newlines = suggestion.count("\n") + suggestion.count("\\n")
    
    if suggest_newlines < source_newlines:
        return False, f"Missing newlines: expected at least {source_newlines}, got {suggest_newlines}"
    
    return True, ""

def check_html(source, suggestion):
    """
    Checks if HTML tags are intact.
    """
    source_tags = set(re.findall(r"<[^>]+>", source))
    suggest_tags = set(re.findall(r"<[^>]+>", suggestion))
    
    if not source_tags.issubset(suggest_tags):
        missing = source_tags - suggest_tags
        return False, f"Missing HTML tags: {', '.join(missing)}"
    
    return True, ""

class GlossaryViolationError(Exception):
    """Raised when an AI suggestion violates glossary rules."""
    pass


def is_arabic_fuzzy_match(term: str, text: str) -> bool:
    """Check if 'term' exists in 'text' with Arabic-aware flexibility (prefixes, suffixes, plurals)."""
    if not term or not text:
        return False
    if term in text:
        return True
    
    # Common Arabic prefixes and suffixes to strip for core matching
    def get_core(s):
        # Strip common prefixes (Al, Li, Bi, Ka, Wa, Fa)
        s = re.sub(r"^(ال|ل|ب|ك|و|ف)", "", s)
        # Remove weak letters/vowels for root-ish comparison (Alef, Waw, Ya, Teh Marbuta)
        return re.sub(r"[اويية]", "", s)

    term_core = get_core(term)
    if not term_core or len(term_core) < 2:
        return term in text
        
    # Split text into words and check each
    words = re.split(r"[^\w\u0600-\u06FF]+", text)
    for word in words:
        if not word: continue
        w_core = get_core(word)
        if term_core in w_core:
            # Check length to ensure it's a derivation, not a random word
            if abs(len(w_core) - len(term_core)) <= 3:
                return True
    return False


def validate_glossary_compliance(suggestion: str, source_text: str, glossary: dict, key: str = "") -> tuple[bool, str]:
    """Strictly validates if the suggestion complies with the provided glossary.
    
    Supports fuzzy matching for Arabic to handle prefixes, suffixes, and plurals.
    Includes technical key patterns and term density checks to avoid false positives.
    """
    if not glossary:
        return True, ""

    # 0. Technical Key / Pattern Ignore List (Bulletproof Recovery)
    technical_prefixes = ("config", "setup", "uuid", "error_code", "zone")
    technical_substr = ("_id", "_url")
    uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

    if key:
        k_lower = key.lower()
        if k_lower.startswith(technical_prefixes) or any(s in k_lower for s in technical_substr) or uuid_pattern.search(key):
            logging.debug(f"Glossary check ignored for technical key: {key}")
            return True, ""

    # 1. Technical Term Density Check
    # If a string contains > 30% technical identifiers (paths, slugs, codes), we lower the enforcement
    tech_identifiers = re.findall(r"[A-Za-z0-9_]{5,}/[A-Za-z0-9_/]+|[a-z0-9_]{10,}", suggestion)
    words = suggestion.split()
    if words:
        tech_ratio = len(tech_identifiers) / len(words)
        if tech_ratio > 0.3:
            logging.debug(f"Glossary check softened: Tech density {tech_ratio:.2f}")
            # We don't return True immediately, but we can be more lenient later if needed.
            # For now, following the user's "Ignore errors" instruction.
            return True, ""

    # Compile term patterns for source text matching
    glossary_terms = []
    for term in glossary.get("terms", []):
        if isinstance(term, dict) and term.get("term_en") and term.get("approved_ar"):
            glossary_terms.append({
                "term_en": str(term["term_en"]),
                "approved_ar": str(term["approved_ar"]),
                "forbidden_ar": [str(i) for i in term.get("forbidden_ar", []) if i],
                "pattern": re.compile(rf"(?<![A-Za-z]){re.escape(str(term['term_en']))}(?![A-Za-z])", re.IGNORECASE)
            })

    # 2. Global forbidden terms (unconditional) - TESTED ON TARGET VALUE ONLY
    rules = glossary.get("rules", {})
    if isinstance(rules, dict):
        for item in rules.get("forbidden_terms", []):
            forbidden = str(item.get("forbidden_ar", ""))
            # VALIDATION ON TARGET (suggestion) ONLY
            if forbidden and forbidden in suggestion:
                use_instead = item.get("use_instead", "an approved term")
                return False, f"Uses forbidden global term '{forbidden}'. Use '{use_instead}' instead."

    # 3. Key-term mapping based on source text - VALIDATION ON TARGET (suggestion) ONLY
    for term in glossary_terms:
        # We only check if the term exists in SOURCE to know if it's required in TARGET
        if term["pattern"].search(source_text):
            approved_ar = term["approved_ar"]
            # Flexible: Approved term check (ON TARGET ONLY)
            if not is_arabic_fuzzy_match(approved_ar, suggestion):
                return False, f"Missing approved glossary term '{approved_ar}' for English term '{term['term_en']}'."
            
            # Strict: Forbidden terms (ON TARGET ONLY)
            for forbidden in term["forbidden_ar"]:
                if is_arabic_fuzzy_match(forbidden, suggestion):
                    return False, f"Uses forbidden glossary term '{forbidden}' for English term '{term['term_en']}'. Use '{approved_ar}' instead."

    return True, ""


def verify_batch_fixes(original_batch, ai_fixes, glossary=None):
    """
    Verifies a batch of AI suggestions.
    Checks placeholders, newlines, HTML tags, and GLOSSARY compliance.
    """
    verified_fixes = []
    source_by_key = {item["key"]: item["source_text"] for item in original_batch if "source_text" in item}
    # Fallback to 'source' if 'source_text' is missing
    if not source_by_key:
        source_by_key = {item["key"]: item.get("source", "") for item in original_batch}
        
    target_by_key = {item["key"]: item.get("current_translation", "") for item in original_batch}
    
    for fix in ai_fixes:
        key = fix.get("key")
        suggestion = fix.get("suggestion")
        
        if not key or not suggestion or key not in source_by_key:
            # Phase 9: output contract violation — key or suggestion missing.
            emit_ai_fallback(
                key=key or "<unknown>",
                reason="output_contract_violation",
                details={"has_key": bool(key), "has_suggestion": bool(suggestion)},
            )
            continue
            
        source_text = source_by_key[key]
        target_text = target_by_key[key]
        
        # Capture original source for reporting if it was pre-processed
        item = next((i for i in original_batch if i.get("key") == key), {})
        original_source = item.get("original_source", source_text)

        # Phase 9: log full AI response in debug mode.
        if is_ai_debug_mode():
            logging.debug("AI RAW RESPONSE [key=%s]: %s", key, fix)
        
        # If suggestion is identical, skip
        if suggestion.strip() == target_text.strip():
            continue
            
        # Basic Verification
        v_tasks = [
            check_placeholders(source_text, suggestion),
            check_newlines(source_text, suggestion),
            check_html(source_text, suggestion)
        ]
        
        # Glossary Verification
        if glossary:
            v_tasks.append(validate_glossary_compliance(suggestion, source_text, glossary, key=key))
        
        failed = [msg for ok, msg in v_tasks if not ok]

        if not failed:
            # --- Phase 5: Semantic acceptance gate ---
            # Runs only after all structural checks pass to avoid redundant work.
            item_context = item.get("context")
            item_placeholders = item.get("placeholders") if isinstance(item.get("placeholders"), list) else None
            semantic_result = evaluate_semantic_acceptance(
                source_text,
                suggestion,
                key=key,
                context=item_context,
                glossary=glossary,
                placeholders=item_placeholders,
            )
            target_text_stripped = target_text.strip()
            has_valid_existing_translation = bool(
                target_text_stripped and target_text_stripped != "[MISSING]"
            )
            outcome = decide_ai_outcome(
                semantic_result["status"],
                has_existing_translation=has_valid_existing_translation,
            )

            # Phase 9: log semantic result in debug mode.
            if is_ai_debug_mode():
                logging.debug(
                    "AI SEMANTIC RESULT [key=%s]: status=%s reason_codes=%s",
                    key, semantic_result["status"], semantic_result["reason_codes"],
                )

            if outcome["decision"] == "reject":
                # Phase 9: fallback event + counter for semantic reject.
                emit_ai_fallback(
                    key=key,
                    reason="semantic_reject",
                    details={"reason_codes": semantic_result["reason_codes"]},
                )
                get_metrics().record_rejected()
                logging.debug(
                    "AI Suggestion for %s rejected by semantic gate: %s",
                    key, semantic_result["reason_codes"],
                )
                continue  # Discard this candidate safely

            verified_fixes.append({
                "key": key,
                "verified": outcome["allow_apply"],
                "needs_review": outcome["needs_review"],
                "issue_type": "ai_suggestion",
                "severity": "info",
                "message": f"AI Suggestion: {fix.get('reason', '')}",
                "source": source_text,
                "original_source": original_source,
                "target": target_text,
                "suggestion": suggestion,
                "extra": {
                    "ai_outcome_decision": outcome["decision"],
                    "semantic_gate_status": semantic_result["status"],
                    "semantic_reason_codes": semantic_result["reason_codes"],
                },
            })

            # Phase 9: trace event + counter for accepted / suspicious outcomes.
            if semantic_result["status"] == "accept":
                emit_ai_decision_trace(
                    key=key,
                    invoked=True,
                    semantic_status="accept",
                    final_decision="safe",
                )
                get_metrics().record_accepted()
            else:
                # suspicious
                emit_ai_decision_trace(
                    key=key,
                    invoked=True,
                    semantic_status=semantic_result["status"],
                    final_decision=outcome["decision"],
                )
                get_metrics().record_suspicious()
        else:
            # Phase 9: fallback event + counter for structural failures.
            emit_ai_fallback(
                key=key,
                reason="structural_failure",
                details={"failures": failed},
            )
            get_metrics().record_rejected()
            logging.debug("AI Suggestion for %s rejected by structural verification: %s", key, failed)
            
    return verified_fixes
