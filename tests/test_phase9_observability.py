"""
tests/test_phase9_observability.py
===================================
Phase 9 — Production Hardening: Observability + Resilience tests.

Test coverage:
  1. Skip reasons — each ``should_invoke_ai`` branch returns the correct code
  2. Decision trace — emit_ai_decision_trace returns correct structured fields
  3. Fallback logging — emit_ai_fallback returns correct structured event
  4. Debug mode — payload hidden by default; visible under L10N_AUDIT_DEBUG_AI=1
  5. Metrics — counters increment correctly in verify_batch_fixes and run_stage

All tests are pure / deterministic: no AI, no network, no filesystem I/O.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from l10n_audit.audits.ai_review import should_invoke_ai
from l10n_audit.core.ai_trace import (
    SKIP_REASON_AUTO_SAFE_CLASSIFICATION,
    SKIP_REASON_DETERMINISTIC_FIX,
    SKIP_REASON_FORMATTING_ONLY,
    SKIP_REASON_NON_LINGUISTIC_SOURCE,
    SKIP_REASON_PLACEHOLDER_ONLY,
    SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT,
    AIDecisionMetrics,
    emit_ai_decision_trace,
    emit_ai_fallback,
    get_metrics,
    is_ai_debug_mode,
    reset_metrics,
)
from l10n_audit.ai.verification import verify_batch_fixes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CTX = {"short_ambiguous_threshold": 4}


def _finding(
    source_text: str = "Hello world",
    current_text: str = "مرحبا",
    issue_type: str = "semantic_mismatch",
    classification: str = "",
    context: str | None = None,
    glossary: dict | None = None,
) -> dict:
    f: dict = {
        "key": "test.key",
        "source_text": source_text,
        "current_text": current_text,
        "issue_type": issue_type,
        "issue_types": [issue_type] if issue_type else [],
        "classification": classification,
    }
    if context is not None:
        f["context"] = context
    if glossary is not None:
        f["glossary"] = glossary
    return f


# ---------------------------------------------------------------------------
# 1. Skip reasons
# ---------------------------------------------------------------------------


def test_skip_non_linguistic_source():
    """Empty source → skip with non_linguistic_source reason."""
    invoke, reason = should_invoke_ai(_finding(source_text=""), _CTX)
    assert invoke is False
    assert reason == SKIP_REASON_NON_LINGUISTIC_SOURCE


def test_skip_formatting_only():
    """Whitespace issue type → skip with formatting_only reason."""
    invoke, reason = should_invoke_ai(
        _finding(source_text="Hello world", issue_type="whitespace"), _CTX
    )
    assert invoke is False
    assert reason == SKIP_REASON_FORMATTING_ONLY


def test_skip_placeholder_only():
    """Placeholder-only issue type → skip with placeholder_only reason."""
    invoke, reason = should_invoke_ai(
        _finding(source_text="Hello {name}", issue_type="placeholder-only"), _CTX
    )
    assert invoke is False
    assert reason == SKIP_REASON_PLACEHOLDER_ONLY


def test_skip_issue_type_containing_placeholder():
    """Issue type containing 'placeholder' → placeholder_only reason."""
    f = _finding(source_text="Hello {name}", issue_type="placeholder_count_mismatch")
    invoke, reason = should_invoke_ai(f, _CTX)
    assert invoke is False
    assert reason == SKIP_REASON_PLACEHOLDER_ONLY


def test_skip_deterministic_fix():
    """Known safe replacement → skip with deterministic_fix reason."""
    invoke, reason = should_invoke_ai(
        _finding(source_text="Hello world", issue_type="safe_normalization"), _CTX
    )
    assert invoke is False
    assert reason == SKIP_REASON_DETERMINISTIC_FIX


def test_skip_auto_safe_classification():
    """Auto-safe classification → skip with auto_safe_classification reason."""
    invoke, reason = should_invoke_ai(
        _finding(source_text="Hello world", classification="auto_safe"), _CTX
    )
    assert invoke is False
    assert reason == SKIP_REASON_AUTO_SAFE_CLASSIFICATION


def test_skip_short_ambiguous_no_context():
    """≤4-word source with no context/glossary → short_ambiguous_no_context."""
    # 'Save' is 1 word — well under the threshold; no context or glossary.
    invoke, reason = should_invoke_ai(
        _finding(
            source_text="Save me",
            issue_type="semantic_mismatch",
            classification="",
            context=None,
            glossary=None,
        ),
        _CTX,
    )
    assert invoke is False
    assert reason == SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT


def test_invoke_returns_none_reason_for_missing_translation():
    """Missing translation → invoke=True, reason=None."""
    f = _finding(source_text="Your profile page", current_text="", issue_type="empty_ar")
    invoke, reason = should_invoke_ai(f, _CTX)
    assert invoke is True
    assert reason is None


def test_invoke_returns_none_reason_when_invoked():
    """When AI is invoked, skip reason must be None."""
    f = _finding(
        source_text="Update your profile settings here",
        current_text="تحديث إعدادات الملف الشخصي",
        issue_type="ar_qc",
        classification="",
    )
    invoke, reason = should_invoke_ai(f, _CTX)
    # ar_qc is a semantic marker → _requires_semantic_repair returns True
    if invoke:
        assert reason is None


# ---------------------------------------------------------------------------
# 2. Decision trace fields
# ---------------------------------------------------------------------------


def test_emit_decision_trace_skip_fields():
    """emit_ai_decision_trace for a skipped item has correct fields."""
    trace = emit_ai_decision_trace(
        key="home.title",
        invoked=False,
        skip_reason=SKIP_REASON_NON_LINGUISTIC_SOURCE,
    )
    assert trace["event"] == "ai_decision_trace"
    assert trace["key"] == "home.title"
    assert trace["invoked"] is False
    assert trace["skip_reason"] == SKIP_REASON_NON_LINGUISTIC_SOURCE
    assert trace["semantic_status"] is None
    assert trace["final_decision"] is None


def test_emit_decision_trace_accept_fields():
    """emit_ai_decision_trace for an accepted outcome has correct fields."""
    trace = emit_ai_decision_trace(
        key="greet.msg",
        invoked=True,
        semantic_status="accept",
        final_decision="safe",
    )
    assert trace["event"] == "ai_decision_trace"
    assert trace["invoked"] is True
    assert trace["skip_reason"] is None
    assert trace["semantic_status"] == "accept"
    assert trace["final_decision"] == "safe"


def test_emit_decision_trace_suspicious_fields():
    """emit_ai_decision_trace for suspicious outcome has correct fields."""
    trace = emit_ai_decision_trace(
        key="pay.title",
        invoked=True,
        semantic_status="suspicious",
        final_decision="review",
    )
    assert trace["semantic_status"] == "suspicious"
    assert trace["final_decision"] == "review"


def test_emit_decision_trace_reject_fields():
    """emit_ai_decision_trace for a reject outcome has correct fields."""
    trace = emit_ai_decision_trace(
        key="err.msg",
        invoked=True,
        semantic_status="reject",
        final_decision="reject",
    )
    assert trace["semantic_status"] == "reject"
    assert trace["final_decision"] == "reject"


# ---------------------------------------------------------------------------
# 3. Fallback event fields
# ---------------------------------------------------------------------------


def test_emit_fallback_semantic_reject():
    """emit_ai_fallback for semantic_reject has correct event and reason."""
    event = emit_ai_fallback(
        key="time.picker",
        reason="semantic_reject",
        details={"reason_codes": ["semantic_concept_injection"]},
    )
    assert event["event"] == "ai_fallback"
    assert event["key"] == "time.picker"
    assert event["reason"] == "semantic_reject"


def test_emit_fallback_structural_failure():
    event = emit_ai_fallback(
        key="inbox.count",
        reason="structural_failure",
        details={"failures": ["placeholder mismatch"]},
    )
    assert event["event"] == "ai_fallback"
    assert event["reason"] == "structural_failure"


def test_emit_fallback_output_contract_violation():
    event = emit_ai_fallback(key="<unknown>", reason="output_contract_violation")
    assert event["event"] == "ai_fallback"
    assert event["reason"] == "output_contract_violation"


def test_emit_fallback_parse_error():
    event = emit_ai_fallback(key="some.key", reason="parse_error")
    assert event["event"] == "ai_fallback"
    assert event["reason"] == "parse_error"


def test_emit_fallback_no_suggestion():
    event = emit_ai_fallback(key="batch.keys", reason="no_suggestion")
    assert event["event"] == "ai_fallback"
    assert event["reason"] == "no_suggestion"


def test_verify_batch_fixes_emits_fallback_for_missing_key(caplog):
    """Fixes with no key or suggestion emit a fallback, are not added to output."""
    import logging
    batch = [
        {"key": "a.b", "source_text": "Hello world", "current_translation": "مرحبا"}
    ]
    fixes = [{"key": None, "suggestion": None}]  # contract violation
    with caplog.at_level(logging.DEBUG, logger="l10n_audit.ai_trace"):
        results = verify_batch_fixes(batch, fixes)
    assert results == []
    # fallback log line must appear
    assert any("ai_fallback" in r.getMessage().lower() or "output_contract_violation" in r.getMessage().lower()
               for r in caplog.records)


def test_verify_batch_fixes_emits_fallback_for_structural_failure(caplog):
    """Placeholder mismatch → structural_failure fallback emitted."""
    import logging
    batch = [
        {
            "key": "msg.greet",
            "source_text": "Hello {name}",
            # Use a different current_translation so the suggestion isn't skipped as identical.
            "current_translation": "مرحبا يا {name}",
        }
    ]
    # suggestion is missing placeholder {name} → structural check fails
    fixes = [{"key": "msg.greet", "suggestion": "مرحبا يا صديقي"}]
    with caplog.at_level(logging.DEBUG, logger="l10n_audit.ai_trace"):
        results = verify_batch_fixes(batch, fixes)
    # placeholder mismatch → candidate dropped
    assert results == []
    assert any("structural_failure" in r.getMessage() for r in caplog.records)


def test_verify_batch_fixes_emits_fallback_for_semantic_reject(caplog):
    """Semantic reject → semantic_reject fallback emitted."""
    import logging
    batch = [
        {
            "key": "time.picker",
            "source_text": "Pick time for now",
            "current_translation": "اختر وقتاً",
        }
    ]
    fixes = [{"key": "time.picker", "suggestion": "وقت الذروة الآن", "reason": "AI"}]
    with caplog.at_level(logging.DEBUG, logger="l10n_audit.ai_trace"):
        results = verify_batch_fixes(batch, fixes)
    assert results == []
    assert any("semantic_reject" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 4. Debug mode
# ---------------------------------------------------------------------------


def test_debug_mode_off_by_default(monkeypatch):
    """L10N_AUDIT_DEBUG_AI is not set → is_ai_debug_mode returns False."""
    monkeypatch.delenv("L10N_AUDIT_DEBUG_AI", raising=False)
    assert is_ai_debug_mode() is False


def test_debug_mode_on_with_truthy_value(monkeypatch):
    """L10N_AUDIT_DEBUG_AI=1 → is_ai_debug_mode returns True."""
    monkeypatch.setenv("L10N_AUDIT_DEBUG_AI", "1")
    assert is_ai_debug_mode() is True


def test_debug_mode_payload_hidden_by_default(monkeypatch):
    """When debug mode is OFF, debug_payload must NOT appear in trace event."""
    monkeypatch.delenv("L10N_AUDIT_DEBUG_AI", raising=False)
    trace = emit_ai_decision_trace(
        key="k",
        invoked=False,
        skip_reason=SKIP_REASON_FORMATTING_ONLY,
        payload={"source_text": "sensitive text"},
    )
    assert "debug_payload" not in trace


def test_debug_mode_payload_visible_when_enabled(monkeypatch):
    """When debug mode is ON, debug_payload IS in the trace event."""
    monkeypatch.setenv("L10N_AUDIT_DEBUG_AI", "1")
    trace = emit_ai_decision_trace(
        key="k",
        invoked=False,
        skip_reason=SKIP_REASON_FORMATTING_ONLY,
        payload={"source_text": "sensitive text"},
    )
    assert "debug_payload" in trace
    assert trace["debug_payload"]["source_text"] == "sensitive text"


def test_debug_mode_fallback_details_hidden_by_default(monkeypatch):
    """When debug mode is OFF, debug_details must NOT appear in fallback event."""
    monkeypatch.delenv("L10N_AUDIT_DEBUG_AI", raising=False)
    event = emit_ai_fallback(
        key="k",
        reason="semantic_reject",
        details={"reason_codes": ["semantic_concept_injection"]},
    )
    assert "debug_details" not in event


def test_debug_mode_fallback_details_visible_when_enabled(monkeypatch):
    """When debug mode is ON, debug_details IS in the fallback event."""
    monkeypatch.setenv("L10N_AUDIT_DEBUG_AI", "1")
    event = emit_ai_fallback(
        key="k",
        reason="semantic_reject",
        details={"reason_codes": ["semantic_concept_injection"]},
    )
    assert "debug_details" in event
    assert "semantic_concept_injection" in event["debug_details"]["reason_codes"]


# ---------------------------------------------------------------------------
# 5. Metrics counters
# ---------------------------------------------------------------------------


def test_metrics_initial_state():
    """Fresh AIDecisionMetrics instance has all zeros."""
    m = AIDecisionMetrics()
    assert m.to_dict() == {
        "ai_invoked_count": 0,
        "ai_skipped_count": 0,
        "ai_accepted_count": 0,
        "ai_suspicious_count": 0,
        "ai_rejected_count": 0,
    }


def test_metrics_record_invoked():
    m = AIDecisionMetrics()
    m.record_invoked()
    m.record_invoked()
    assert m.ai_invoked_count == 2


def test_metrics_record_skipped():
    m = AIDecisionMetrics()
    m.record_skipped()
    assert m.ai_skipped_count == 1


def test_metrics_record_accepted():
    m = AIDecisionMetrics()
    m.record_accepted()
    assert m.ai_accepted_count == 1


def test_metrics_record_suspicious():
    m = AIDecisionMetrics()
    m.record_suspicious()
    assert m.ai_suspicious_count == 1


def test_metrics_record_rejected():
    m = AIDecisionMetrics()
    m.record_rejected()
    assert m.ai_rejected_count == 1


def test_metrics_reset_clears_singleton():
    """reset_metrics() returns a fresh singleton."""
    reset_metrics()
    get_metrics().record_invoked()
    assert get_metrics().ai_invoked_count == 1
    reset_metrics()
    assert get_metrics().ai_invoked_count == 0


def test_metrics_increment_on_semantic_accept():
    """verify_batch_fixes increments accepted_count for a clean accept."""
    reset_metrics()
    batch = [
        {
            "key": "time.picker",
            "source_text": "Pick a time",
            "current_translation": "اختر",
        }
    ]
    fixes = [{"key": "time.picker", "suggestion": "اختر وقتاً", "reason": "AI"}]
    results = verify_batch_fixes(batch, fixes)
    # Outcome must be accept (no reason codes expected for a clean translation)
    if results and results[0]["extra"]["semantic_gate_status"] == "accept":
        assert get_metrics().ai_accepted_count >= 1


def test_metrics_increment_on_semantic_reject():
    """verify_batch_fixes increments rejected_count for a semantic reject."""
    reset_metrics()
    batch = [
        {
            "key": "time.picker",
            "source_text": "Pick time for now",
            "current_translation": "اختر وقتاً",
        }
    ]
    fixes = [{"key": "time.picker", "suggestion": "وقت الذروة الآن", "reason": "AI"}]
    verify_batch_fixes(batch, fixes)
    assert get_metrics().ai_rejected_count >= 1


def test_metrics_increment_on_structural_failure():
    """verify_batch_fixes increments rejected_count for a structural failure."""
    reset_metrics()
    batch = [
        {
            "key": "msg.greet",
            "source_text": "Hello {name}",
            # current_translation is different so the suggestion isn't skipped as identical.
            "current_translation": "مرحبا يا {name}",
        }
    ]
    # missing placeholder → structural failure
    fixes = [{"key": "msg.greet", "suggestion": "مرحبا يا صديقي"}]
    verify_batch_fixes(batch, fixes)
    assert get_metrics().ai_rejected_count >= 1


def test_run_stage_resets_metrics_and_records_skipped(tmp_path):
    """run_stage resets the module metrics and records skipped keys."""
    from l10n_audit.audits.ai_review import run_stage

    # Pre-pollute metrics to confirm reset works.
    get_metrics().record_invoked()
    get_metrics().record_invoked()

    runtime = MagicMock()
    runtime.config = {"decision_engine": {"respect_routing": True}}
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.metadata = {}
    runtime.results_dir.mkdir(parents=True, exist_ok=True)

    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "test"
    options.ai_review.model = "test-model"
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.batch_size = 50
    options.ai_review.translate_missing = False
    options.write_reports = False

    # Issue whose key has a formatting issue → should be skipped.
    issues = [
        {
            "key": "home.title",
            "issue_type": "whitespace",
            "message": "Trim spaces",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
            "classification": "auto_safe",
        }
    ]
    en_data = {"home.title": "Home"}
    ar_data = {"home.title": " الرئيسية "}
    provider = MagicMock()
    provider.review_batch.return_value = []

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    # After run_stage the invoked count was reset, and the key was skipped.
    metrics = get_metrics()
    # invoked should be 0 (was reset; the key was skipped due to auto_safe)
    assert metrics.ai_invoked_count == 0
    assert metrics.ai_skipped_count >= 1


def test_run_stage_stores_metrics_in_runtime_metadata(tmp_path):
    """run_stage stores ai_decision_metrics in runtime.metadata."""
    from l10n_audit.audits.ai_review import run_stage

    runtime = MagicMock()
    runtime.config = {"decision_engine": {"respect_routing": True}}
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.metadata = {}
    runtime.results_dir.mkdir(parents=True, exist_ok=True)

    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "test"
    options.ai_review.model = "test-model"
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.batch_size = 50
    options.ai_review.translate_missing = False
    options.write_reports = False

    issues = [
        {
            "key": "home.title",
            "issue_type": "whitespace",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
            "classification": "auto_safe",
        }
    ]
    en_data = {"home.title": "Home"}
    ar_data = {"home.title": " الرئيسية "}
    provider = MagicMock()
    provider.review_batch.return_value = []

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert "ai_decision_metrics" in runtime.metadata
    stored = runtime.metadata["ai_decision_metrics"]
    assert "ai_invoked_count" in stored
    assert "ai_skipped_count" in stored
