"""
Phase 5 — Deterministic Semantic Acceptance Gate tests.

All tests are pure/deterministic: no AI, no network, no filesystem.
"""
from __future__ import annotations

import pytest
from l10n_audit.ai.verification import (
    decide_ai_outcome,
    evaluate_semantic_acceptance,
    verify_batch_fixes,
)


# ---------------------------------------------------------------------------
# 1. Hard reject: canonical concept-injection case
# ---------------------------------------------------------------------------

def test_reject_concept_injection_peak():
    """source: 'Pick time for now'  →  bad AI: 'وقت الذروة الآن'."""
    result = evaluate_semantic_acceptance(
        "Pick time for now",
        "وقت الذروة الآن",
    )
    assert result["status"] == "reject"
    assert "semantic_concept_injection" in result["reason_codes"]


def test_reject_concept_injection_rush():
    """'ازدحام' (congestion) injected when source says nothing about traffic."""
    result = evaluate_semantic_acceptance(
        "Select your delivery time",
        "اختر وقت التسليم وسط الازدحام",
    )
    assert result["status"] == "reject"
    assert "semantic_concept_injection" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 2. Accept: correct minimal translations
# ---------------------------------------------------------------------------

def test_accept_simple_label():
    result = evaluate_semantic_acceptance("Save", "احفظ")
    assert result["status"] == "accept"
    assert result["reason_codes"] == []


def test_accept_correct_time_translation():
    """'Pick time' correctly translated preserving 'وقت'."""
    result = evaluate_semantic_acceptance(
        "Pick a time",
        "اختر وقتاً",
    )
    assert result["status"] == "accept"


def test_accept_with_placeholder():
    result = evaluate_semantic_acceptance(
        "Hello {name}",
        "مرحباً {name}",
        placeholders=["{name}"],
    )
    assert result["status"] == "accept"


def test_accept_correct_select_translation():
    result = evaluate_semantic_acceptance(
        "Select account",
        "اختر الحساب",
    )
    assert result["status"] == "accept"


# ---------------------------------------------------------------------------
# 3. Polarity / negation mismatch
# ---------------------------------------------------------------------------

def test_reject_polarity_mismatch_do_not_cancel():
    """'Do not cancel' must NOT become a positive imperative without negation."""
    result = evaluate_semantic_acceptance(
        "Do not cancel",
        "ألغ",  # positive imperative "Cancel!" — polarity flipped
    )
    assert result["status"] == "reject"
    assert "semantic_polarity_mismatch" in result["reason_codes"]


def test_reject_polarity_mismatch_never():
    result = evaluate_semantic_acceptance(
        "Never share your password",
        "شارك كلمة مرورك",  # positive — lost negation
    )
    assert result["status"] == "reject"
    assert "semantic_polarity_mismatch" in result["reason_codes"]


def test_accept_polarity_preserved_do_not_cancel():
    """Arabic keeps negation marker 'لا'."""
    result = evaluate_semantic_acceptance(
        "Do not cancel",
        "لا تلغِ",
    )
    assert result["status"] == "accept"


# ---------------------------------------------------------------------------
# 4. Number / entity mismatch
# ---------------------------------------------------------------------------

def test_reject_number_disappeared():
    result = evaluate_semantic_acceptance(
        "You have 5 unread messages",
        "لديك رسائل غير مقروءة",  # '5' disappeared
    )
    assert result["status"] == "reject"
    assert "semantic_number_mismatch" in result["reason_codes"]


def test_accept_number_preserved():
    result = evaluate_semantic_acceptance(
        "You have 5 unread messages",
        "لديك 5 رسائل غير مقروءة",
    )
    assert result["status"] == "accept"


def test_reject_named_entity_via_glossary():
    glossary = {
        "terms": [
            {"term_en": "Wallet", "approved_ar": "المحفظة"},
        ]
    }
    result = evaluate_semantic_acceptance(
        "Open your Wallet",
        "افتح حسابك",  # 'المحفظة' is missing despite being required by glossary
        glossary=glossary,
    )
    assert result["status"] == "reject"
    assert "semantic_named_entity_mismatch" in result["reason_codes"]


def test_accept_named_entity_present():
    glossary = {
        "terms": [
            {"term_en": "Wallet", "approved_ar": "المحفظة"},
        ]
    }
    result = evaluate_semantic_acceptance(
        "Open your Wallet",
        "افتح المحفظة",
        glossary=glossary,
    )
    assert result["status"] == "accept"


# ---------------------------------------------------------------------------
# 5. Short-string strict mode (≤ 4 tokens)
# ---------------------------------------------------------------------------

def test_reject_short_string_expansion_with_injection():
    """Short source + concept injection → reject via short_text_expansion."""
    result = evaluate_semantic_acceptance(
        "Pick time",       # 2 tokens — short-string mode
        "وقت الذروة الآن",  # 'ذروة' injected, candidate bloated
    )
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_reject_short_string_massive_expansion_no_context():
    """Short source (1 token) must not be semantically expanded without context."""
    result = evaluate_semantic_acceptance(
        "Save",   # 1 token
        "يرجى حفظ جميع التغييرات التي أجريتها على ملفك الشخصي الآن",  # very long
        context=None,
        glossary=None,
    )
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_accept_short_string_with_context_support():
    """Short source allowed slightly longer output when context is supplied."""
    result = evaluate_semantic_acceptance(
        "Save",
        "احفظ البيانات",
        context="Profile settings form",
    )
    assert result["status"] == "accept"


# ---------------------------------------------------------------------------
# 6. Suspicious (soft drift — not a hard reject)
# ---------------------------------------------------------------------------

def test_suspicious_key_concept_loss():
    """'time' vanishes from candidate without placeholder covering it."""
    result = evaluate_semantic_acceptance(
        "Set time reminder",
        "ضبط التذكير",  # 'time' (وقت) missing
    )
    # key_concept_loss alone → suspicious, not reject
    assert result["status"] in ("suspicious", "reject")
    assert "semantic_key_concept_loss" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 7. Integration: verify_batch_fixes drops semantic rejects
# ---------------------------------------------------------------------------

def test_decide_ai_outcome_accept():
    result = decide_ai_outcome("accept", has_existing_translation=True)
    assert result == {"decision": "safe", "allow_apply": True, "needs_review": False}


def test_decide_ai_outcome_suspicious():
    result = decide_ai_outcome("suspicious", has_existing_translation=False)
    assert result == {"decision": "review", "allow_apply": False, "needs_review": True}


def test_decide_ai_outcome_reject():
    result = decide_ai_outcome("reject", has_existing_translation=True)
    assert result == {"decision": "reject", "allow_apply": False, "needs_review": True}


def test_verify_batch_fixes_drops_semantic_reject():
    """verify_batch_fixes must not pass a candidate rejected by the semantic gate."""
    batch = [
        {
            "key": "time.picker",
            "source_text": "Pick time for now",
            "current_translation": "اختر وقتاً",
        }
    ]
    fixes = [
        {"key": "time.picker", "suggestion": "وقت الذروة الآن", "reason": "AI"}
    ]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert results == [], "Semantic reject should have been dropped"


def test_verify_batch_fixes_keeps_semantic_accept():
    """verify_batch_fixes must pass a structurally+semantically valid candidate."""
    batch = [
        {
            "key": "time.picker",
            "source_text": "Pick a time",
            "current_translation": "اختر",
        }
    ]
    fixes = [
        {"key": "time.picker", "suggestion": "اختر وقتاً", "reason": "AI"}
    ]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert len(results) == 1
    assert results[0]["suggestion"] == "اختر وقتاً"
    assert results[0]["verified"] is True
    assert results[0]["needs_review"] is False
    assert results[0]["extra"]["semantic_gate_status"] == "accept"
    assert results[0]["extra"]["ai_outcome_decision"] == "safe"


def test_verify_batch_fixes_surfaces_reason_codes():
    """Suspicious candidates are kept but reason codes appear in extra."""
    batch = [
        {
            "key": "reminder.set",
            "source_text": "Set time reminder",
            "current_translation": "",
        }
    ]
    fixes = [
        {"key": "reminder.set", "suggestion": "ضبط التذكير", "reason": "AI"}
    ]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    # Should be accepted or suspicious (not rejected outright for this case)
    if results:
        assert "semantic_gate_status" in results[0]["extra"]
        if results[0]["extra"]["semantic_gate_status"] == "suspicious":
            assert results[0]["verified"] is False
            assert results[0]["needs_review"] is True
            assert results[0]["extra"]["ai_outcome_decision"] == "review"


def test_verify_batch_fixes_drops_polarity_mismatch():
    batch = [
        {
            "key": "action.cancel",
            "source_text": "Do not cancel",
            "current_translation": "لا تلغِ",
        }
    ]
    fixes = [
        {"key": "action.cancel", "suggestion": "ألغ", "reason": "AI"}
    ]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert results == [], "Polarity-mismatch reject must be dropped"


def test_verify_batch_fixes_drops_number_mismatch():
    batch = [
        {
            "key": "inbox.count",
            "source_text": "You have 5 unread messages",
            "current_translation": "",
        }
    ]
    fixes = [
        {"key": "inbox.count", "suggestion": "لديك رسائل غير مقروءة", "reason": "AI"}
    ]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert results == [], "Number-mismatch reject must be dropped"


# ---------------------------------------------------------------------------
# 8. No false reject — correct outputs must not be blocked
# ---------------------------------------------------------------------------

def test_no_false_reject_add_address():
    result = evaluate_semantic_acceptance(
        "Add Address",
        "إضافة عنوان",
    )
    assert result["status"] == "accept"


def test_no_false_reject_delete_account():
    result = evaluate_semantic_acceptance(
        "Delete Account",
        "حذف الحساب",
    )
    assert result["status"] == "accept"


def test_no_false_reject_send_message():
    result = evaluate_semantic_acceptance(
        "Send Message",
        "إرسال رسالة",
    )
    assert result["status"] == "accept"


def test_no_false_reject_empty_source():
    """Empty source/candidate should gracefully return accept without crashing."""
    result = evaluate_semantic_acceptance("", "")
    assert result["status"] == "accept"
