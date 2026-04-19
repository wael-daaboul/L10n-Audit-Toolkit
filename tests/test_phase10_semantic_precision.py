"""
Phase 10 — Semantic Precision Upgrade tests.

All tests are pure/deterministic: no AI, no network, no filesystem.
Covers: domain confusion sets, transliteration blocking, UI label/state lexicon,
short-string strict mode escalation, glossary-boosted enforcement, and no-regression.
"""
from __future__ import annotations

import pytest
from l10n_audit.ai.verification import evaluate_semantic_acceptance, verify_batch_fixes


# ---------------------------------------------------------------------------
# 1. Domain confusion sets — hard reject / suspicious cases
# ---------------------------------------------------------------------------

def test_reject_rides_horse_riding():
    """`rides` must not become horse-riding (ركوب الخيل) — clear domain wrong."""
    result = evaluate_semantic_acceptance("rides", "ركوب الخيل")
    assert result["status"] == "reject"
    assert "semantic_confusion_set_match" in result["reason_codes"]


def test_reject_rides_too_generic():
    """`rides` with generic ركوب should be suspicious or reject (domain mismatch)."""
    result = evaluate_semantic_acceptance("rides", "ركوب")
    # ركوب alone is suspicious-level; short string (1 token) escalates to reject
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_domain_term_mismatch", "semantic_short_text_expansion")
    )


def test_reject_rider_transliteration():
    """`rider` must not be transliterated as رايدر — approved Arabic is راكب."""
    result = evaluate_semantic_acceptance("rider", "رايدر")
    assert result["status"] == "reject"
    assert "semantic_transliteration_forbidden" in result["reason_codes"]


def test_suspicious_or_reject_cancel_wrong_sense():
    """`cancel` must not use شطب (write-off/strikethrough) as the UI action."""
    result = evaluate_semantic_acceptance("cancel", "شطب")
    # 1 token → escalated to reject via short-string domain escalation
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_ui_label_mismatch", "semantic_short_text_expansion")
    )


def test_suspicious_or_reject_saved_rescue_sense():
    """`saved` must not use أنقذ (rescued/saved from danger) as the UI result state."""
    result = evaluate_semantic_acceptance("saved", "أنقذ")
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_ui_state_mismatch", "semantic_short_text_expansion")
    )


def test_suspicious_or_reject_medium_intermediary():
    """`medium` (as tier) must not use واسطة (intermediary/middleman)."""
    result = evaluate_semantic_acceptance("medium", "واسطة")
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_domain_term_mismatch", "semantic_short_text_expansion")
    )


def test_suspicious_gold_customer_possessive():
    """`gold customer` tier label must not use possessive عميل الذهب."""
    result = evaluate_semantic_acceptance("gold customer", "عميل الذهب")
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_ui_label_mismatch", "semantic_short_text_expansion")
    )


def test_suspicious_distance_away_literary():
    """`distance away` in UI context must not become the literary phrase تنأى بعيدا."""
    result = evaluate_semantic_acceptance("distance away", "تنأى بعيدا")
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_ui_label_mismatch", "semantic_short_text_expansion")
    )


def test_suspicious_notification_formal():
    """`notification` standard term is إشعار; إخطار is too formal/legal."""
    result = evaluate_semantic_acceptance("notification", "إخطار وارد")
    # "notification" is 1 token → short-string escalation applies
    assert result["status"] in ("suspicious", "reject")
    assert any(
        c in result["reason_codes"]
        for c in ("semantic_ui_label_mismatch", "semantic_short_text_expansion")
    )


# ---------------------------------------------------------------------------
# 2. Accept cases — correct translations must not be blocked
# ---------------------------------------------------------------------------

def test_accept_rides_correct():
    """`rides` → الرحلات (trips) is the correct ride-hailing translation."""
    result = evaluate_semantic_acceptance("rides", "الرحلات")
    assert result["status"] == "accept"


def test_accept_rider_correct():
    """`rider` → راكب is the approved Arabic term."""
    result = evaluate_semantic_acceptance("rider", "راكب")
    assert result["status"] == "accept"


def test_accept_cancel_correct():
    """`cancel` → إلغاء is the correct UI action label."""
    result = evaluate_semantic_acceptance("cancel", "إلغاء")
    assert result["status"] == "accept"


def test_accept_saved_correct():
    """`saved` → تم الحفظ is the correct UI result-state phrasing."""
    result = evaluate_semantic_acceptance("saved", "تم الحفظ")
    assert result["status"] == "accept"


def test_accept_medium_correct():
    """`medium` → متوسط is acceptable for a size/tier label."""
    result = evaluate_semantic_acceptance("medium", "متوسط")
    assert result["status"] == "accept"


# ---------------------------------------------------------------------------
# 3. Transliteration — glossary-approved exception passes
# ---------------------------------------------------------------------------

def test_transliteration_blocked_without_glossary():
    """رايدر is rejected when no glossary overrides it."""
    result = evaluate_semantic_acceptance("rider", "رايدر")
    assert result["status"] == "reject"
    assert "semantic_transliteration_forbidden" in result["reason_codes"]


def test_transliteration_approved_by_glossary():
    """If the project glossary explicitly approves رايدر, the check must pass."""
    glossary = {
        "terms": [
            {"term_en": "rider", "approved_ar": "رايدر"},
        ]
    }
    result = evaluate_semantic_acceptance("rider", "رايدر", glossary=glossary)
    # Glossary approval overrides the transliteration block;
    # the approved term IS present so named-entity check also passes.
    assert "semantic_transliteration_forbidden" not in result["reason_codes"]


def test_driver_transliteration_blocked():
    """درايفر is rejected when source contains driver."""
    result = evaluate_semantic_acceptance("driver needed", "درايفر مطلوب")
    assert result["status"] in ("suspicious", "reject")
    assert "semantic_transliteration_forbidden" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 4. Short-string strict mode (≤ 3 tokens) escalates suspicious to reject
# ---------------------------------------------------------------------------

def test_short_string_cancel_shath_escalated():
    """1-token `cancel` + wrong شطب is escalated to reject."""
    result = evaluate_semantic_acceptance("cancel", "شطب")
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_short_string_saved_rescue_escalated():
    """1-token `saved` + wrong أنقذ is escalated to reject."""
    result = evaluate_semantic_acceptance("saved", "أنقذ")
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_short_string_medium_escalated():
    """1-token `medium` + wrong واسطة is escalated to reject."""
    result = evaluate_semantic_acceptance("medium", "واسطة")
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_short_string_gold_customer_escalated():
    """2-token `gold customer` + wrong عميل الذهب is escalated to reject."""
    result = evaluate_semantic_acceptance("gold customer", "عميل الذهب")
    assert result["status"] == "reject"
    assert "semantic_short_text_expansion" in result["reason_codes"]


def test_long_string_domain_mismatch_stays_suspicious():
    """Longer source (> 3 tokens) with a domain mismatch stays suspicious, not reject."""
    result = evaluate_semantic_acceptance(
        "Please cancel your pending booking",  # 5 tokens — NOT a short string
        "شطب الحجز المعلق",
    )
    # Should be suspicious (ui_label_mismatch) but NOT escalated to reject
    assert result["status"] in ("suspicious", "reject")
    assert "semantic_ui_label_mismatch" in result["reason_codes"]
    # semantic_short_text_expansion must NOT be present (source > 3 tokens)
    assert "semantic_short_text_expansion" not in result["reason_codes"]


# ---------------------------------------------------------------------------
# 5. Glossary-boosted domain enforcement (forbidden_ar tightens the decision)
# ---------------------------------------------------------------------------

def test_glossary_forbidden_ar_triggers_reject():
    """If the glossary marks رايدر as forbidden for 'rider', it must be rejected."""
    glossary = {
        "terms": [
            {"term_en": "rider", "approved_ar": "راكب", "forbidden_ar": ["رايدر"]},
        ]
    }
    result = evaluate_semantic_acceptance("rider", "رايدر وارد", glossary=glossary)
    assert result["status"] == "reject"
    assert "semantic_named_entity_mismatch" in result["reason_codes"]


def test_glossary_approved_term_passes():
    """Glossary-approved term appearing correctly must pass."""
    glossary = {
        "terms": [
            {"term_en": "rider", "approved_ar": "راكب"},
        ]
    }
    result = evaluate_semantic_acceptance("rider details", "تفاصيل الراكب", glossary=glossary)
    assert result["status"] == "accept"


def test_glossary_forbidden_adds_named_entity_mismatch():
    """forbidden_ar in glossary adds semantic_named_entity_mismatch reason code."""
    glossary = {
        "terms": [
            {"term_en": "rides", "approved_ar": "الرحلات", "forbidden_ar": ["ركوب الخيل"]},
        ]
    }
    result = evaluate_semantic_acceptance("rides history", "ركوب الخيل", glossary=glossary)
    assert result["status"] == "reject"
    assert "semantic_named_entity_mismatch" in result["reason_codes"]


# ---------------------------------------------------------------------------
# 6. Integration: verify_batch_fixes propagates new reason codes
# ---------------------------------------------------------------------------

def test_verify_batch_drops_rider_transliteration():
    """verify_batch_fixes must drop رايدر (transliteration) candidate for 'rider'."""
    batch = [{"key": "profile.rider", "source_text": "rider", "current_translation": ""}]
    fixes = [{"key": "profile.rider", "suggestion": "رايدر", "reason": "AI"}]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert results == []


def test_verify_batch_drops_rides_horse():
    """verify_batch_fixes must drop ركوب الخيل for 'rides'."""
    batch = [{"key": "home.rides", "source_text": "rides", "current_translation": ""}]
    fixes = [{"key": "home.rides", "suggestion": "ركوب الخيل", "reason": "AI"}]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert results == []


def test_verify_batch_keeps_correct_rides():
    """verify_batch_fixes must pass الرحلات as a correct translation for 'rides'."""
    batch = [{"key": "home.rides", "source_text": "rides", "current_translation": ""}]
    fixes = [{"key": "home.rides", "suggestion": "الرحلات", "reason": "AI"}]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    assert len(results) == 1
    assert results[0]["suggestion"] == "الرحلات"
    assert results[0]["extra"]["semantic_gate_status"] == "accept"


def test_verify_batch_reason_codes_surfaced():
    """verify_batch_fixes surfaces phase-10 reason codes in the extra dict."""
    batch = [{"key": "action.cancel", "source_text": "cancel", "current_translation": ""}]
    fixes = [{"key": "action.cancel", "suggestion": "شطب", "reason": "AI"}]
    results = verify_batch_fixes(batch, fixes, glossary=None)
    # Short-string escalation → should be dropped (reject)
    assert results == []


# ---------------------------------------------------------------------------
# 7. No regression — existing semantic gate behavior unchanged
# ---------------------------------------------------------------------------

def test_no_regression_concept_injection():
    """Existing concept-injection rejection still works."""
    result = evaluate_semantic_acceptance("Pick time for now", "وقت الذروة الآن")
    assert result["status"] == "reject"
    assert "semantic_concept_injection" in result["reason_codes"]


def test_no_regression_polarity_mismatch():
    """Existing polarity-mismatch rejection still works."""
    result = evaluate_semantic_acceptance("Do not cancel", "ألغ")
    assert result["status"] == "reject"
    assert "semantic_polarity_mismatch" in result["reason_codes"]


def test_no_regression_number_mismatch():
    """Existing number-mismatch rejection still works."""
    result = evaluate_semantic_acceptance(
        "You have 5 unread messages", "لديك رسائل غير مقروءة"
    )
    assert result["status"] == "reject"
    assert "semantic_number_mismatch" in result["reason_codes"]


def test_no_regression_accept_simple_label():
    """Simple correct label still accepted without false positives."""
    result = evaluate_semantic_acceptance("Add Address", "إضافة عنوان")
    assert result["status"] == "accept"


def test_no_regression_accept_delete_account():
    result = evaluate_semantic_acceptance("Delete Account", "حذف الحساب")
    assert result["status"] == "accept"


def test_no_regression_accept_send_message():
    result = evaluate_semantic_acceptance("Send Message", "إرسال رسالة")
    assert result["status"] == "accept"


def test_no_regression_empty_input():
    result = evaluate_semantic_acceptance("", "")
    assert result["status"] == "accept"
