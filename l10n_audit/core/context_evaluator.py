#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from l10n_audit.core.languagetool_layer import get_languagetool_layer, lt_findings_to_signal_dict


SENTENCE_END_RE = re.compile(r"[.!?؟]$")
WORD_RE = re.compile(r"[A-Za-z\u0600-\u06FF0-9]+")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}|\{[^{}]+\}")

ACTION_CUE_MAP = {
    "add": ("أضف", "إضافة"),
    "save": ("احفظ", "حفظ"),
    "send": ("أرسل", "إرسال"),
    "delete": ("احذف", "حذف"),
    "approve": ("وافق", "موافقة"),
    "select": ("اختر", "اختيار"),
    "enter": ("أدخل", "إدخال"),
}

TEXT_TYPE_HINTS = {
    "button": {"button", "btn", "cta", "submit", "save", "cancel"},
    "title": {"title", "heading", "header", "screen_title"},
    "subtitle": {"subtitle", "sub_title", "caption"},
    "helper_text": {"helper", "hint", "instruction", "details", "description", "helper_text", "note"},
    "dialog_title": {"dialog_title", "alert_title", "modal_title"},
    "dialog_body": {"dialog_body", "dialog_message", "alert_message", "modal_body"},
    "snackbar": {"snackbar", "toast", "flash_message"},
    "notification_title": {"notification_title"},
    "notification_body": {"notification_body", "push_body"},
    "form_label": {"label", "field", "name"},
    "form_hint": {"hint", "placeholder"},
}


def split_key_tokens(key: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized)
    return [token.lower() for token in normalized.split("_") if token]


def is_sentence_like(text: str) -> bool:
    stripped = text.strip()
    words = WORD_RE.findall(stripped)
    return bool(stripped) and (len(words) >= 7 or "\n" in stripped or bool(SENTENCE_END_RE.search(stripped)))


def is_short_label(text: str) -> bool:
    stripped = text.strip()
    words = WORD_RE.findall(stripped)
    return bool(stripped) and len(words) <= 3 and not SENTENCE_END_RE.search(stripped)


def infer_text_type(key: str, en_value: str, usage_locations: list[str]) -> str:
    if usage_locations:
        preferred = [item for item in usage_locations if item != "unknown"]
        if preferred:
            counts = Counter(preferred)
            return counts.most_common(1)[0][0]

    tokens = set(split_key_tokens(key))
    token_matches = [(text_type, len(tokens & hints)) for text_type, hints in TEXT_TYPE_HINTS.items() if tokens & hints]
    if token_matches:
        priority = {
            "dialog_title": 0,
            "dialog_body": 1,
            "notification_title": 2,
            "notification_body": 3,
            "helper_text": 4,
            "form_hint": 5,
            "form_label": 6,
            "subtitle": 7,
            "title": 8,
            "button": 9,
        }
        token_matches.sort(key=lambda item: (-item[1], priority.get(item[0], 100), item[0]))
        return token_matches[0][0]

    lowered = en_value.strip().lower()
    if is_sentence_like(en_value):
        if any(token in lowered for token in ("please", "tap", "click", "add ", "enter ", "select ", "to ")):
            return "helper_text"
        return "subtitle"
    if is_short_label(en_value):
        return "button"
    return "text"


def _dominant_hint(values: list[str] | None, fallback: str = "") -> str:
    filtered = [value for value in (values or []) if value and value != "unknown" and value != "generic"]
    if not filtered:
        return fallback
    counts = Counter(filtered)
    return counts.most_common(1)[0][0]


def english_sentence_shape(en_value: str) -> str:
    if is_sentence_like(en_value):
        return "sentence_like"
    if is_short_label(en_value):
        return "short_label"
    return "phrase"


def arabic_sentence_shape(ar_value: str) -> str:
    stripped = ar_value.strip()
    words = WORD_RE.findall(stripped)
    if not stripped:
        return "empty"
    if len(words) >= 7 or "\n" in stripped or bool(SENTENCE_END_RE.search(stripped)):
        return "sentence_like"
    if len(words) <= 3:
        return "short_label"
    return "phrase"


def action_mismatch_flags(en_value: str, ar_value: str) -> list[str]:
    en_lower = en_value.casefold()
    flags: list[str] = []
    for term, arabic_candidates in ACTION_CUE_MAP.items():
        if term in en_lower and not any(candidate in ar_value for candidate in arabic_candidates):
            flags.append(f"missing_action:{term}")
    return flags


def _extract_semantic_cues(text: str) -> set[str]:
    lowered = text.casefold()
    cues: set[str] = set()

    shape = english_sentence_shape(text) if re.search(r"[A-Za-z]", text) else arabic_sentence_shape(text)
    cues.add(f"shape:{shape}")

    for action_key, arabic_candidates in ACTION_CUE_MAP.items():
        if action_key in lowered or any(candidate in text for candidate in arabic_candidates):
            cues.add(f"action:{action_key}")

    for placeholder in PLACEHOLDER_RE.findall(text):
        cues.add(f"placeholder:{placeholder}")

    for number in re.findall(r"\d+", text):
        cues.add(f"number:{number}")

    return cues


def semantic_similarity(source_text: str, target_text: str) -> float:
    """Return a deterministic semantic cue similarity in [0.0, 1.0].

    This is intentionally heuristic and explainable: it compares language-agnostic
    semantic cues such as action intent, placeholders, numbers, and sentence shape.
    It does not attempt probabilistic or embedding-based meaning inference.
    """
    source_cues = _extract_semantic_cues(source_text)
    target_cues = _extract_semantic_cues(target_text)

    if not source_cues and not target_cues:
        return 1.0

    union = source_cues | target_cues
    if not union:
        return 1.0
    return round(len(source_cues & target_cues) / len(union), 4)


def load_en_languagetool_signals(results_dir: Path) -> dict[str, dict[str, Any]]:
    # Try grammar report
    report_path = results_dir / ".cache" / "raw_tools" / "grammar" / "grammar_audit_report.json"
    if not report_path.exists():
        # Fallback to legacy
        report_path = results_dir / "per_tool" / "grammar" / "grammar_audit_report.json"
    if not report_path.exists():
        return {}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in payload.get("findings", []):
        if isinstance(row, dict):
            grouped[str(row.get("key", ""))].append(row)

    signals: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        issue_types = Counter(str(row.get("issue_type", "")).lower() for row in rows)
        rule_ids = [str(row.get("rule_id", "")) for row in rows if row.get("rule_id")]
        literal_support = any("style" in issue_type or "grammar" in issue_type for issue_type in issue_types)
        signals[key] = {
            "lt_style_flags": issue_types.get("style", 0),
            "lt_grammar_flags": issue_types.get("grammar", 0),
            "lt_literalness_support": literal_support,
            "lt_rule_ids": rule_ids[:5],
            "sources": ["languagetool"],
        }
    return signals


def build_language_tool_python_signals(ar_data: dict[str, object], runtime) -> dict[str, dict[str, Any]]:
    # Defer check to after we check Java availability.
    from l10n_audit.core.utils import check_java_available
    if not check_java_available():
        return {}
    
    layer = get_languagetool_layer(runtime, "ar")
    if layer is None:
        return {}

    # Map the incoming data values to what layer.analyze_text_batch expects.
    # Only submit valid non-empty strings.
    text_by_key = [
        (str(key), str(value))
        for key, value in ar_data.items()
        if isinstance(value, str) and value.strip()
    ]

    if not text_by_key:
        layer.close()
        return {}

    try:
        # strict=False (default) swallows per-item exceptions and continues,
        # which EXACTLY mirrors the previous `try / except Exception: continue` logic.
        findings = layer.analyze_text_batch(text_by_key, strict=False)
        
        # Phase 1 / Step 5: Decision Engine hook (no-op)
        # NOTE:
        # Arabic pipeline must remain behaviorally identical in Phase 1.
        # Decision Engine integration will be introduced in Phase 2.
        
        return dict(lt_findings_to_signal_dict(findings, session_mode=layer.session_mode))
    finally:
        layer.close()



def merge_linguistic_signals(*signal_sets: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    merged: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"lt_style_flags": 0, "lt_grammar_flags": 0, "lt_literalness_support": False, "lt_rule_ids": [], "sources": []})
    for signal_set in signal_sets:
        for key, payload in signal_set.items():
            target = merged[key]
            target["lt_style_flags"] += int(payload.get("lt_style_flags", 0))
            target["lt_grammar_flags"] += int(payload.get("lt_grammar_flags", 0))
            target["lt_literalness_support"] = bool(target["lt_literalness_support"] or payload.get("lt_literalness_support"))
            for rule_id in payload.get("lt_rule_ids", []):
                if rule_id and rule_id not in target["lt_rule_ids"]:
                    target["lt_rule_ids"].append(rule_id)
            for source in payload.get("sources", []):
                if source not in target["sources"]:
                    target["sources"].append(source)
    return dict(merged)


def english_term_flags(en_value: str, role_identifiers: list[str] | None = None, entity_whitelist_en: list[str] | None = None) -> list[str]:
    lowered = en_value.casefold()
    flags = []
    combined = sorted(set((role_identifiers or []) + (entity_whitelist_en or [])))
    for term in combined:
        if term in lowered:
            flags.append(f"en:{term}")
    return flags


def arabic_role_flags(ar_value: str, role_identifiers: list[str] | None = None, entity_whitelist_ar: list[str] | None = None) -> list[str]:
    flags = []
    for term in sorted(role_identifiers or []):
        if term in ar_value:
            flags.append(f"ar_person:{term}")
    for term in sorted(entity_whitelist_ar or []):
        if term in ar_value:
            flags.append(f"ar_entity:{term}")
    return flags


def evaluate_candidate_change(
    bundle: dict[str, Any], 
    candidate_text: str,
    role_identifiers: list[str] | None = None,
    entity_whitelist: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    flags = list(bundle.get("context_sensitive_term_flags", []))
    semantic_risk = "low"
    evidence_reasons: list[str] = []
    inferred_text_type = str(bundle.get("inferred_text_type", "text"))
    en_value = str(bundle.get("en_value", ""))
    ar_value = str(bundle.get("ar_value", ""))
    current_shape = str(bundle.get("arabic_sentence_shape", ""))
    candidate_shape = arabic_sentence_shape(candidate_text)
    expected_shape = str(bundle.get("english_sentence_shape", ""))
    text_role = str(bundle.get("text_role", ""))
    action_hint = str(bundle.get("action_hint", ""))
    current_similarity = float(bundle.get("current_semantic_similarity", semantic_similarity(en_value, ar_value)))
    candidate_similarity = semantic_similarity(en_value, candidate_text)
    similarity_drop = round(max(0.0, current_similarity - candidate_similarity), 4)
    shape_preserved = expected_shape == candidate_shape or (
        expected_shape == "phrase" and candidate_shape == current_shape
    )
    action_preserved = not any(flag.startswith("missing_action:") for flag in action_mismatch_flags(en_value, candidate_text))
    entity_alignment_ok = True

    if bundle.get("has_context_sensitive_terms") and candidate_text.strip() != ar_value.strip():
        semantic_risk = "medium"
        evidence_reasons.append("context_sensitive_term_risk")

    en_lower = en_value.casefold()
    # Check if candidate mentions a person role when the source mentioned an entity/admin term
    candidate_person = any(term in candidate_text for term in (role_identifiers or []))
    ar_entity = (entity_whitelist or {}).get("ar", [])
    en_entity = (entity_whitelist or {}).get("en", [])
    current_entity = any(term in ar_value for term in ar_entity)
    source_is_entity = any(term in en_lower for term in en_entity)
    
    if source_is_entity and candidate_person and current_entity:
        semantic_risk = "high"
        flags.append("role_entity_misalignment")
        evidence_reasons.append("role_entity_misalignment")
        entity_alignment_ok = False

    if (is_sentence_like(en_value) or inferred_text_type in {"helper_text", "subtitle", "dialog_body", "notification_body"}) and is_short_label(candidate_text):
        semantic_risk = "high"
        flags.append("structural_mismatch")
        evidence_reasons.append("structural_mismatch")
        shape_preserved = False

    if expected_shape == "sentence_like" and candidate_shape == "short_label":
        semantic_risk = "high"
        flags.append("sentence_collapse")
        evidence_reasons.append("sentence_collapse")
        shape_preserved = False

    if current_shape == "sentence_like" and candidate_shape == "short_label":
        semantic_risk = "high"
        flags.append("sentence_collapse")
        evidence_reasons.append("sentence_collapse")
        shape_preserved = False

    if text_role == "message" and candidate_shape == "short_label" and expected_shape != "short_label":
        semantic_risk = "high"
        flags.append("message_label_mismatch")
        evidence_reasons.append("message_label_mismatch")
        shape_preserved = False

    if action_hint == "action" and expected_shape == "sentence_like" and candidate_shape == "short_label":
        semantic_risk = "high"
        flags.append("action_loss")
        evidence_reasons.append("action_loss")
        action_preserved = False

    if candidate_similarity < 0.35 and similarity_drop >= 0.15:
        if semantic_risk != "high":
            semantic_risk = "high" if not shape_preserved or not action_preserved else "medium"
        flags.append("semantic_similarity_low")
        evidence_reasons.append("semantic_similarity_low")
    elif candidate_similarity < 0.55 and similarity_drop >= 0.1 and semantic_risk == "low":
        semantic_risk = "medium"
        flags.append("semantic_similarity_medium")
        evidence_reasons.append("semantic_similarity_drop")

    if not shape_preserved and semantic_risk == "low":
        semantic_risk = "medium"
    if not action_preserved and semantic_risk == "low":
        semantic_risk = "medium"
    if not entity_alignment_ok and semantic_risk != "high":
        semantic_risk = "high"

    semantic_evidence = {
        "current_semantic_similarity": current_similarity,
        "candidate_semantic_similarity": candidate_similarity,
        "similarity_drop": similarity_drop,
        "shape_preserved": shape_preserved,
        "action_preserved": action_preserved,
        "entity_alignment_ok": entity_alignment_ok,
    }

    reason_fragments: list[str] = []
    if "role_entity_misalignment" in evidence_reasons:
        reason_fragments.append("role/entity alignment changed")
    if "sentence_collapse" in evidence_reasons or "structural_mismatch" in evidence_reasons or "message_label_mismatch" in evidence_reasons:
        reason_fragments.append("sentence shape was not preserved")
    if "action_loss" in evidence_reasons:
        reason_fragments.append("action intent was not preserved")
    if "semantic_similarity_low" in evidence_reasons or "semantic_similarity_drop" in evidence_reasons:
        reason_fragments.append(
            f"semantic similarity dropped from {current_similarity:.2f} to {candidate_similarity:.2f}"
        )
    if "context_sensitive_term_risk" in evidence_reasons and not reason_fragments:
        reason_fragments.append("context-sensitive role/entity ambiguity remains")

    return {
        "context_flags": sorted(set(flags)),
        "semantic_risk": semantic_risk,
        "review_required": semantic_risk in {"medium", "high"},
        "review_reason": "; ".join(reason_fragments).strip(),
        "semantic_similarity": candidate_similarity,
        "semantic_evidence": semantic_evidence,
    }


def build_context_bundle(
    key: str,
    en_value: str,
    ar_value: str,
    *,
    usage_locations: list[str] | None = None,
    usage_metadata: dict[str, Any] | None = None,
    linguistic_signals: dict[str, Any] | None = None,
    role_identifiers: list[str] | None = None,
    entity_whitelist: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    usage_locations = sorted(set(usage_locations or []))
    usage_metadata = usage_metadata or {}
    inferred_text_type = infer_text_type(key, en_value, usage_locations)
    key_tokens = split_key_tokens(key)
    
    entity_en = (entity_whitelist or {}).get("en", [])
    entity_ar = (entity_whitelist or {}).get("ar", [])
    
    risk_flags = english_term_flags(en_value, role_identifiers, entity_en) + arabic_role_flags(ar_value, role_identifiers, entity_ar)
    risk_flags.extend(action_mismatch_flags(en_value, ar_value))
    ui_surface = _dominant_hint(list(usage_metadata.get("ui_surfaces", [])), "generic")
    fallback_text_role = "body"
    if inferred_text_type in {"helper_text", "subtitle", "dialog_body", "notification_body", "form_hint", "snackbar", "toast"}:
        fallback_text_role = "message"
    elif inferred_text_type in {"button", "title", "dialog_title", "notification_title", "form_label"}:
        fallback_text_role = "label"
    text_role = _dominant_hint(list(usage_metadata.get("text_roles", [])), fallback_text_role)
    action_hint = _dominant_hint(list(usage_metadata.get("action_hints", [])), "action" if any(token in en_value.casefold() for token in ("add", "save", "send", "delete", "select", "enter", "approve")) else "inform")
    audience_hint = _dominant_hint(list(usage_metadata.get("audience_hints", [])), "role_specific" if any(flag.startswith("en:") for flag in risk_flags) else "general")
    sentence_shape = _dominant_hint(list(usage_metadata.get("sentence_shapes", [])), english_sentence_shape(en_value))
    semantic_flags = sorted(set(risk_flags))
    signals = {
        "lt_style_flags": int((linguistic_signals or {}).get("lt_style_flags", 0)),
        "lt_grammar_flags": int((linguistic_signals or {}).get("lt_grammar_flags", 0)),
        "lt_literalness_support": bool((linguistic_signals or {}).get("lt_literalness_support", False)),
        "lt_rule_ids": list((linguistic_signals or {}).get("lt_rule_ids", [])),
        "sources": list((linguistic_signals or {}).get("sources", [])),
    }
    semantic_risk = "medium" if semantic_flags else "low"
    review_reason = ""
    if semantic_flags:
        review_reason = "Possible person/department or role/entity ambiguity. Human review required."
        if any(flag.startswith("missing_action:") for flag in semantic_flags):
            review_reason = "Possible meaning loss in the Arabic sentence. Human review required."
    current_similarity = semantic_similarity(en_value, ar_value)

    return {
        "key": key,
        "en_value": en_value,
        "ar_value": ar_value,
        "normalized_key_shape": key_tokens,
        "inferred_text_type": inferred_text_type,
        "ui_surface": ui_surface,
        "text_role": text_role,
        "action_hint": action_hint,
        "audience_hint": audience_hint,
        "english_sentence_shape": english_sentence_shape(en_value),
        "arabic_sentence_shape": arabic_sentence_shape(ar_value),
        "usage_sentence_shape": sentence_shape,
        "usage_locations": usage_locations,
        "usage_metadata": {
            "ui_surfaces": list(usage_metadata.get("ui_surfaces", [])),
            "text_roles": list(usage_metadata.get("text_roles", [])),
            "action_hints": list(usage_metadata.get("action_hints", [])),
            "audience_hints": list(usage_metadata.get("audience_hints", [])),
            "sentence_shapes": list(usage_metadata.get("sentence_shapes", [])),
        },
        "linguistic_signals": signals,
        "context_sensitive_term_flags": semantic_flags,
        "semantic_flags": semantic_flags,
        "has_context_sensitive_terms": bool(semantic_flags),
        "semantic_risk": semantic_risk,
        "review_reason": review_reason,
        "current_semantic_similarity": current_similarity,
    }
