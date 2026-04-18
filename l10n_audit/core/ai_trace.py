"""
l10n_audit/core/ai_trace.py
============================
Phase 9 — Observability layer for AI decision tracing.

Provides:
  - Skip reason constants (deterministic codes surfaced in trace events)
  - AIDecisionMetrics — in-memory per-run counters (no external persistence)
  - emit_ai_decision_trace() — structured trace event logging
  - emit_ai_fallback() — fallback event logging for discarded candidates
  - is_ai_debug_mode() — checks L10N_AUDIT_DEBUG_AI env flag

Hard constraints (Phase 9):
  * No changes to decision logic or safety behaviour.
  * No external I/O beyond Python logging.
  * All public functions are pure side-effects (logging + counter updates).
  * Module-level singleton is reset-able via reset_metrics() for test isolation.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("l10n_audit.ai_trace")

# ---------------------------------------------------------------------------
# Debug mode flag (Part 5)
# ---------------------------------------------------------------------------

_DEBUG_AI_FLAG = "L10N_AUDIT_DEBUG_AI"
_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


def is_ai_debug_mode() -> bool:
    """Return True when ``L10N_AUDIT_DEBUG_AI`` is set to a truthy value."""
    return str(os.environ.get(_DEBUG_AI_FLAG, "")).strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Skip reason constants (Part 2)
# ---------------------------------------------------------------------------

SKIP_REASON_NON_LINGUISTIC_SOURCE: str = "non_linguistic_source"
"""Source text is empty, a UUID, a URL-slug, or otherwise non-translatable."""

SKIP_REASON_FORMATTING_ONLY: str = "formatting_only"
"""Issue is a pure formatting/whitespace/punctuation/spacing fix — AI adds no value."""

SKIP_REASON_PLACEHOLDER_ONLY: str = "placeholder_only"
"""Issue is placeholder-only; deterministic rules already handle it."""

SKIP_REASON_DETERMINISTIC_FIX: str = "deterministic_fix"
"""Issue type has a known deterministic replacement; AI is not needed."""

SKIP_REASON_AUTO_SAFE_CLASSIFICATION: str = "auto_safe_classification"
"""Finding was already classified as auto-safe; no AI review needed."""

SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT: str = "short_ambiguous_no_context"
"""Source is short (≤ threshold tokens) with neither glossary nor UI context."""


# ---------------------------------------------------------------------------
# In-memory metrics counters (Part 4)
# ---------------------------------------------------------------------------


class AIDecisionMetrics:
    """Thread-unsafe in-memory counters for one pipeline run.

    Counters:
        ai_invoked_count     — keys whose payload was queued for AI
        ai_skipped_count     — keys filtered out by ``should_invoke_ai``
        ai_accepted_count    — candidates whose semantic gate returned "accept"
        ai_suspicious_count  — candidates flagged "suspicious" by semantic gate
        ai_rejected_count    — candidates dropped (semantic reject or structural failure)
    """

    __slots__ = (
        "ai_invoked_count",
        "ai_skipped_count",
        "ai_accepted_count",
        "ai_suspicious_count",
        "ai_rejected_count",
    )

    def __init__(self) -> None:
        self.ai_invoked_count: int = 0
        self.ai_skipped_count: int = 0
        self.ai_accepted_count: int = 0
        self.ai_suspicious_count: int = 0
        self.ai_rejected_count: int = 0

    # ------------------------------------------------------------------
    # Increment helpers
    # ------------------------------------------------------------------

    def record_invoked(self) -> None:
        self.ai_invoked_count += 1

    def record_skipped(self) -> None:
        self.ai_skipped_count += 1

    def record_accepted(self) -> None:
        self.ai_accepted_count += 1

    def record_suspicious(self) -> None:
        self.ai_suspicious_count += 1

    def record_rejected(self) -> None:
        self.ai_rejected_count += 1

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, int]:
        return {
            "ai_invoked_count": self.ai_invoked_count,
            "ai_skipped_count": self.ai_skipped_count,
            "ai_accepted_count": self.ai_accepted_count,
            "ai_suspicious_count": self.ai_suspicious_count,
            "ai_rejected_count": self.ai_rejected_count,
        }

    def log_summary(self) -> None:
        """Emit an INFO-level summary.  Safe to call at end of run."""
        d = self.to_dict()
        total = d["ai_invoked_count"] + d["ai_skipped_count"]
        logger.info(
            "AI Decision Summary: total_candidates=%d invoked=%d skipped=%d "
            "accepted=%d suspicious=%d rejected=%d",
            total,
            d["ai_invoked_count"],
            d["ai_skipped_count"],
            d["ai_accepted_count"],
            d["ai_suspicious_count"],
            d["ai_rejected_count"],
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_metrics: AIDecisionMetrics = AIDecisionMetrics()


def get_metrics() -> AIDecisionMetrics:
    """Return the module-level ``AIDecisionMetrics`` singleton."""
    return _default_metrics


def reset_metrics() -> None:
    """Replace the module-level singleton with a fresh instance.

    Intended for test isolation — call at the start of each test that
    inspects metric counts.
    """
    global _default_metrics  # noqa: PLW0603
    _default_metrics = AIDecisionMetrics()


# ---------------------------------------------------------------------------
# Structured trace events (Parts 1, 3)
# ---------------------------------------------------------------------------


def emit_ai_decision_trace(
    *,
    key: str,
    invoked: bool,
    skip_reason: str | None = None,
    semantic_status: str | None = None,
    final_decision: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, log, and return a structured AI decision trace event.

    The returned dict is suitable for storage in runtime metadata or tests.

    Parameters
    ----------
    key:
        The translation key being processed.
    invoked:
        ``True`` when the AI was (or will be) called for this key;
        ``False`` when it was filtered out by the invocation guard.
    skip_reason:
        One of the ``SKIP_REASON_*`` constants; set only when ``invoked=False``.
    semantic_status:
        ``"accept"`` | ``"suspicious"`` | ``"reject"`` from the semantic gate;
        ``None`` when the AI was skipped or the result is not yet known.
    final_decision:
        ``"safe"`` | ``"review"`` | ``"reject"`` from ``decide_ai_outcome``;
        ``None`` when the AI was skipped.
    payload:
        Full AI input payload — logged **only** in debug mode to avoid
        leaking potentially sensitive text in default logs.
    """
    trace: dict[str, Any] = {
        "event": "ai_decision_trace",
        "key": key,
        "invoked": invoked,
        "skip_reason": skip_reason,
        "semantic_status": semantic_status,
        "final_decision": final_decision,
    }

    if is_ai_debug_mode():
        if payload is not None:
            trace["debug_payload"] = payload
        logger.debug("AI DECISION TRACE [debug]: %s", trace)
    else:
        logger.debug("AI DECISION TRACE: %s", trace)

    return trace


def emit_ai_fallback(
    *,
    key: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, log, and return a structured AI fallback event.

    A fallback event signals that an AI candidate was **discarded** before
    reaching the output.  Possible reasons:

    * ``"output_contract_violation"`` — AI response missing key or suggestion
    * ``"structural_failure"`` — placeholder / newline / HTML check failed
    * ``"semantic_reject"`` — ``decide_ai_outcome`` returned ``"reject"``
    * ``"parse_error"`` — JSON parse failure in the provider layer
    * ``"no_suggestion"`` — provider returned an empty response

    Parameters
    ----------
    key:
        Translation key whose candidate was discarded (use ``"<unknown>"``
        when the key cannot be determined).
    reason:
        Short code identifying the discard reason (see above).
    details:
        Optional supplementary dict — logged **only** in debug mode to
        avoid verbose output in the default log stream.
    """
    event: dict[str, Any] = {
        "event": "ai_fallback",
        "key": key,
        "reason": reason,
    }

    if is_ai_debug_mode():
        if details:
            event["debug_details"] = details
        logger.debug("AI FALLBACK [debug]: %s", event)
    else:
        logger.debug("AI FALLBACK [key=%s reason=%s]", key, reason)

    return event
