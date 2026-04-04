#!/usr/bin/env python3
"""
l10n_audit/core/languagetool_layer.py
======================================
Phase 1 / Step 1 — LanguageTool Layer (isolated, not wired into pipeline yet).
Phase 1 / Step 2 — Signal alignment bridge added (``lt_findings_to_signal_dict``).

This module is a thin normalization wrapper above ``languagetool_manager``.
It provides:

* A normalized finding structure (``LTFinding``) derived from raw LT matches.
* A deterministic, category-based classifier (``classify_simple_issue``).
* A safe factory (``get_languagetool_layer``) that returns ``None`` when LT
  is unavailable instead of raising.
* A batch-analysis entry point (``LanguageToolLayer.analyze_text_batch``).
* A signal-alignment bridge (``lt_findings_to_signal_dict``) that converts
  ``list[LTFinding]`` into the exact signal dict shape produced by
  ``context_evaluator.build_language_tool_python_signals``, enabling future
  callers to switch to the layer without changing downstream consumers.

Design constraints
------------------
* Does **not** alter severity, classification, or report shape.
* Does **not** wire into any existing audit stage, engine, or CLI.
* Does **not** read or write files.
* Does **not** call AI.
* All behavior is safe-by-default: an unavailable LT session yields ``None``,
  not an exception.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from collections import defaultdict
from typing import Any, Iterable

from l10n_audit.core.languagetool_manager import create_language_tool_session
from l10n_audit.core.utils import check_java_available

logger = logging.getLogger("l10n_audit.languagetool_layer")

# ---------------------------------------------------------------------------
# Simple-fix category set
# Conservative: only categories whose fixes are provably mechanical and safe.
# Style, typography, confused-words, and semantics are intentionally excluded.
# ---------------------------------------------------------------------------
_SIMPLE_CATEGORIES: frozenset[str] = frozenset(
    {
        "grammar",
        "typos",
        "spelling",
        "whitespace",
    }
)

# Regex used to collapse internal whitespace in LT message strings.
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Public output structure
# ---------------------------------------------------------------------------


@dataclass
class LTFinding:
    """Normalized representation of a single LanguageTool match.

    Fields map 1-to-1 to what ``en_grammar_audit`` already extracts so that
    a future Decision Engine can consume either source without conversion.

    ``is_simple_fix`` is the only new field — it is a read-only classification
    tag derived from ``issue_category`` only.  It does **not** trigger any
    action on its own.
    """

    key: str
    rule_id: str
    issue_category: str   # LT category.id, lowercased
    message: str
    original_text: str
    suggested_text: str   # empty string when no replacement is available
    offset: int
    error_length: int
    is_simple_fix: bool

    # Carry-through fields for backward-compatible dict conversion.
    # These preserve fields that exist in the raw LT match but are not needed
    # for classification.  They allow ``en_grammar_audit`` to reconstruct the
    # existing dict shape without re-parsing the raw match object.
    replacements_str: str = ""  # comma-joined first-3 replacement values
    match_context: str = ""    # LT match context string (display only)

    # Adaptive routing extended metadata (Phase 7)
    confidence_score: float = 0.5
    risk_level: str = "low"


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def classify_simple_issue(issue_category: str) -> bool:
    """Return ``True`` only for clearly mechanical, safe-to-fix LT categories.

    The classifier is intentionally conservative: an unknown or ambiguous
    category always returns ``False``.  Category string is normalised to
    lowercase before comparison.

    Parameters
    ----------
    issue_category:
        The LT ``category.id`` string, already lowercased or not — casing
        is handled internally.
    """
    return issue_category.strip().lower() in _SIMPLE_CATEGORIES


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------


class LanguageToolLayer:
    """Thin normalization layer over a live ``LanguageToolSession``.

    Do not instantiate directly — use :func:`get_languagetool_layer`.
    """

    def __init__(self, session, language: str) -> None:
        self._session = session
        self._language = language
        self._closed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_text_batch(
        self,
        text_by_key: Iterable[tuple[str, str]],
        *,
        strict: bool = False,
    ) -> list[LTFinding]:
        """Run LT checks on a batch of ``(key, text)`` pairs.

        Parameters
        ----------
        text_by_key:
            Iterable of ``(locale_key, source_text)`` pairs.
        strict:
            When ``False`` (default), per-item check exceptions are logged and
            skipped — the batch continues.  When ``True``, the first exception
            from ``session.tool.check()`` is re-raised immediately.  Use
            ``strict=True`` when the caller needs abort-on-first-error
            semantics (e.g. ``en_grammar_audit.build_languagetool_findings``).

        Returns
        -------
        list[LTFinding]
            One :class:`LTFinding` per LT match.  Returns ``[]`` for empty
            input or whitespace-only strings.  In non-strict mode, also
            returns ``[]`` for a failed per-item check.
        """
        pairs = list(text_by_key)
        if not pairs:
            return []

        findings: list[LTFinding] = []
        for key, text in pairs:
            if not text or not text.strip():
                continue
            try:
                matches = self._session.tool.check(text)
            except Exception as exc:
                if strict:
                    raise
                logger.debug(
                    "LT check failed for key=%r: %s", key, exc
                )
                continue
            for match in matches:
                findings.append(self._normalize_match(key, text, match))

        return findings

    def close(self) -> None:
        """Release the underlying LT session.  Safe to call multiple times."""
        if self._closed:
            return
        self._closed = True
        try:
            self._session.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing LT session: %s", exc)

    @property
    def session_mode(self) -> str:
        """Mode string from the underlying session (e.g. ``"local bundled server"``)."""
        return str(self._session.mode)

    @property
    def session_note(self) -> str | None:
        """Optional informational note from the underlying session."""
        return self._session.note or None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_match(
        self,
        key: str,
        original_text: str,
        match: object,
    ) -> LTFinding:
        """Convert a raw ``language_tool_python`` match into an ``LTFinding``."""
        # Replacements — list of objects with a `.value` attribute or plain str
        raw_replacements = getattr(match, "replacements", []) or []
        replacements = [
            str(getattr(item, "value", item)) for item in raw_replacements[:3]
        ]

        # Position
        offset = int(getattr(match, "offset", 0) or 0)
        error_length = int(
            getattr(match, "errorLength", None)
            or getattr(match, "error_length", 0)
            or 0
        )

        # Construct the suggested text from the *first* replacement only
        suggested_text = ""
        if replacements:
            suggested_text = (
                original_text[:offset]
                + replacements[0]
                + original_text[offset + error_length :]
            )

        # Category — normalize to lowercase; default to empty string (not "Unknown")
        # so callers can distinguish "no category" from a real category name.
        raw_category = (
            getattr(getattr(match, "category", None), "id", "") or ""
        )
        issue_category = raw_category.strip().lower()

        # Rule ID and message
        rule_id = str(getattr(match, "ruleId", "") or "")
        raw_message = str(getattr(match, "message", "") or "")
        message = _WHITESPACE_RE.sub(" ", raw_message).strip()

        # Carry-through fields for backward-compatible dict conversion.
        replacements_str = ", ".join(replacements)
        raw_ctx = getattr(match, "context", original_text)
        match_context = _WHITESPACE_RE.sub(" ", str(raw_ctx)).strip()

        return LTFinding(
            key=key,
            rule_id=rule_id,
            issue_category=issue_category,
            message=message,
            original_text=original_text,
            suggested_text=suggested_text,
            offset=offset,
            error_length=error_length,
            is_simple_fix=classify_simple_issue(issue_category),
            replacements_str=replacements_str,
            match_context=match_context,
        )


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def get_languagetool_layer(
    runtime: object,
    language: str,
) -> LanguageToolLayer | None:
    """Return a :class:`LanguageToolLayer` backed by a live LT session.

    Returns ``None`` — not an exception — when LT is unavailable for any
    reason (Java absent, library not installed, server startup failed, etc.).
    Callers must check the return value before use.

    Parameters
    ----------
    runtime:
        A fully loaded :class:`~l10n_audit.core.audit_runtime.AuditPaths`
        instance (or any object with the same attributes expected by
        ``create_language_tool_session``).
    language:
        BCP-47 language tag, e.g. ``"en-US"`` or ``"ar"``.
    """
    if not check_java_available():
        logger.debug(
            "get_languagetool_layer: Java unavailable — returning None"
        )
        return None

    try:
        session = create_language_tool_session(language, runtime)
    except Exception as exc:
        logger.debug(
            "get_languagetool_layer: session creation raised %s — returning None",
            exc,
        )
        return None

    if session.tool is None:
        logger.debug(
            "get_languagetool_layer: session.tool is None (%s) — returning None",
            session.note,
        )
        return None

    return LanguageToolLayer(session, language)


# ---------------------------------------------------------------------------
# Signal alignment bridge
# ---------------------------------------------------------------------------


def lt_findings_to_signal_dict(
    findings: list[LTFinding],
    session_mode: str = "languagetool_layer",
) -> dict[str, dict[str, Any]]:
    """Convert a flat ``list[LTFinding]`` into the per-key signal dict shape.

    The output is **identical in field names and types** to what
    ``context_evaluator.build_language_tool_python_signals`` returns, so it
    can be passed directly to ``merge_linguistic_signals`` without any
    adapter.

    This function makes **no LT calls**.  It is a pure, stateless data
    converter that maps already-normalized ``LTFinding`` objects to the
    aggregated signal shape expected by ``build_context_bundle``.

    Parameters
    ----------
    findings:
        Output of :meth:`LanguageToolLayer.analyze_text_batch`.
    session_mode:
        Free-form source label recorded in the ``"sources"`` list of each
        signal entry.  Defaults to ``"languagetool_layer"`` so downstream
        consumers can distinguish the origin from a raw LT session.

    Returns
    -------
    dict[str, dict[str, Any]]
        ``{ locale_key: signal_dict }`` where each ``signal_dict`` matches
        the shape produced by ``build_language_tool_python_signals``:

        .. code-block:: python

            {
                "lt_style_flags": int,
                "lt_grammar_flags": int,
                "lt_literalness_support": bool,
                "lt_rule_ids": list[str],
                "sources": list[str],
            }
    """
    # Group findings by key using an accumulator.
    # Using defaultdict avoids repeated key-existence checks.
    per_key: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "lt_style_flags": 0,
            "lt_grammar_flags": 0,
            "lt_literalness_support": False,
            "lt_rule_ids": [],
            "sources": [session_mode],
        }
    )

    for finding in findings:
        entry = per_key[finding.key]

        # Increment category counters — mirrors the Counter logic in
        # build_language_tool_python_signals (lines 177-181 of context_evaluator).
        cat = finding.issue_category  # already lowercase
        if cat == "style":
            entry["lt_style_flags"] += 1
            entry["lt_literalness_support"] = True
        elif cat == "grammar":
            entry["lt_grammar_flags"] += 1

        # Collect up to 5 unique rule IDs per key — mirrors [:5] slice in
        # build_language_tool_python_signals (line 182 of context_evaluator).
        if finding.rule_id and len(entry["lt_rule_ids"]) < 5:
            if finding.rule_id not in entry["lt_rule_ids"]:
                entry["lt_rule_ids"].append(finding.rule_id)

    return dict(per_key)
