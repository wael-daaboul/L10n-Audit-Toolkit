#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAMeL Shadow Review Layer — post-build_review_queue decorator.

``decorate_with_camel`` is called **after** ``build_review_queue()`` returns
its fully-suppressed, final list of rows.  It adds ``camel_*`` analysis
columns to each row without modifying any existing field or altering row
count.  The decorated rows are written to ``review_queue.xlsx`` and
``review_projection.json`` so reviewers can evaluate CAMeL results visually.

Contract
--------
* Input row count == output row count (always).
* No existing key is mutated or deleted.
* On per-row failure all ``camel_*`` keys are set to ``""`` and the row is
  still returned — row count is never reduced by an analysis error.
* When ``camel_enabled`` is ``False`` (or the attribute / config key is absent)
  the function returns the rows unchanged, with all ``camel_*`` keys set to
  ``""`` (so downstream column renderers see a consistent schema).
"""

from __future__ import annotations

from typing import Any

CAMEL_FIELDS: list[str] = [
    "camel_available",
    "camel_reason",
    "camel_mixed_script",
    "camel_unknown_count",
    "camel_unknown_tokens",
    "camel_pos_summary",
    "camel_dialect",
    "camel_normalized_preview",
]

_EMPTY_CAMEL: dict[str, str] = {field: "" for field in CAMEL_FIELDS}


def _camel_enabled(runtime: Any) -> bool:
    """Return True only when the runtime explicitly enables CAMeL analysis."""
    # Direct attribute takes precedence (tests can set it directly).
    flag = getattr(runtime, "camel_enabled", None)
    if flag is not None:
        return bool(flag)
    # Fall back to the effective config dict that every subsystem uses.
    cfg = getattr(runtime, "config", None) or {}
    return bool(cfg.get("camel_enabled", False))


def _analyse_row(row: dict[str, Any]) -> dict[str, str]:
    """Run CAMeL analysis on a single review row and return camel_* results.

    This is the integration point for the real CAMeL backend.  The current
    implementation is a **stub** that returns empty strings for every field;
    it will be replaced with a live backend call once the CAMeL dependency is
    available.  The stub guarantees the decorator contract is met from day one:
    all camel_* keys are present and all existing keys are untouched.
    """
    # TODO: replace with live CAMeL backend call, e.g.:
    #   from camel.analyze import analyse_text
    #   result = analyse_text(row.get("old_value", ""), lang="ar")
    #   return {
    #       "camel_available":         "yes",
    #       "camel_reason":            result.reason,
    #       "camel_mixed_script":      str(result.mixed_script),
    #       "camel_unknown_count":     str(result.unknown_count),
    #       "camel_unknown_tokens":    " ".join(result.unknown_tokens),
    #       "camel_pos_summary":       result.pos_summary,
    #       "camel_dialect":           result.dialect,
    #       "camel_normalized_preview": result.normalized_preview,
    #   }
    return dict(_EMPTY_CAMEL)


def decorate_with_camel(
    rows: list[dict[str, Any]],
    runtime: Any,
) -> list[dict[str, Any]]:
    """Add ``camel_*`` shadow analysis columns to each row.

    Parameters
    ----------
    rows:
        Output of ``build_review_queue()`` — fully-suppressed, final rows.
        Must not be modified in place; a new list is returned.
    runtime:
        The ``AuditPaths`` instance (or any duck-typed object) that carries
        ``camel_enabled`` / ``config["camel_enabled"]``.

    Returns
    -------
    list[dict]:
        Same-length list.  Each dict is a shallow copy of the input row with
        ``camel_*`` keys appended.  When CAMeL is disabled or analysis fails
        all ``camel_*`` keys are ``""``.
    """
    decorated: list[dict[str, Any]] = []

    if not _camel_enabled(runtime):
        for row in rows:
            out = dict(row)
            out.update(_EMPTY_CAMEL)
            decorated.append(out)
        return decorated

    for row in rows:
        out = dict(row)
        try:
            camel_result = _analyse_row(row)
        except Exception:
            camel_result = dict(_EMPTY_CAMEL)
        out.update(camel_result)
        decorated.append(out)

    return decorated
