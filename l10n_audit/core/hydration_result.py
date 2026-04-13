#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hydration_result.py — canonical hydration output contract.

Defines HydrationResult: the structural output of a single locale key
resolution and value-lookup attempt.  All five fields map directly to the
canonical contract fields defined in Phase 2 R1 and the resolver output
contract defined in Phase 4.

This module is the canonical home for:
  - HydrationResult (frozen dataclass)
  - LOOKUP_STATUS_* / LOOKUP_RESOLVER_* constants
  - UNRESOLVED_LOOKUP_SOURCE_HASH sentinel

Lifecycle position: complete — stable after Step 5 cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Lookup Status values
# These mirror the six canonical states from the Phase 2 R1 contract.
# Kept as plain string constants rather than an enum to remain compatible
# with the existing codebase's preference for string comparisons.
# ---------------------------------------------------------------------------

LOOKUP_STATUS_NOT_HYDRATED: str = "not_hydrated"
"""Initial state: hydration has not yet been attempted."""

LOOKUP_STATUS_RESOLVED: str = "resolved"
"""Key found in the data store with a non-empty value."""

LOOKUP_STATUS_RESOLVED_EMPTY: str = "resolved_empty"
"""Key found in the data store; its value is the empty string."""

LOOKUP_STATUS_UNRESOLVED: str = "unresolved"
"""Key not found by direct match or any resolution strategy."""

LOOKUP_STATUS_AMBIGUOUS: str = "ambiguous"
"""Key matched multiple candidates via suffix matching; cannot pick one."""

LOOKUP_STATUS_MISSING_LOCALE: str = "missing_locale"
"""The locale data store itself is absent or could not be loaded."""

LOOKUP_STATUS_INVALID_KEY: str = "invalid_key"
"""The canonical key is structurally malformed (empty, None, etc.)."""

# Convenience set of all terminal statuses (i.e. anything after hydration ran)
TERMINAL_LOOKUP_STATUSES: frozenset[str] = frozenset({
    LOOKUP_STATUS_RESOLVED,
    LOOKUP_STATUS_RESOLVED_EMPTY,
    LOOKUP_STATUS_UNRESOLVED,
    LOOKUP_STATUS_AMBIGUOUS,
    LOOKUP_STATUS_MISSING_LOCALE,
    LOOKUP_STATUS_INVALID_KEY,
})

# ---------------------------------------------------------------------------
# Sentinel values
# ---------------------------------------------------------------------------

UNRESOLVED_LOOKUP_SOURCE_HASH: str = "__UNRESOLVED_LOOKUP__"
"""
Sentinel source_hash used whenever the resolver cannot produce a live value.

This constant is the primary authoritative definition.  report_aggregator.py
re-exports it for backward compatibility with existing consumers that import
it from the report layer.  New code must import from this module directly.
"""

# ---------------------------------------------------------------------------
# Lookup Resolver values
# ---------------------------------------------------------------------------

LOOKUP_RESOLVER_DIRECT: str = "direct"
"""Key was found verbatim in the data store."""

LOOKUP_RESOLVER_SUFFIX_MATCH: str = "suffix_match"
"""Key was resolved by unambiguous dot-separated suffix matching."""

LOOKUP_RESOLVER_PREFIX_STRIP: str = "prefix_strip"
"""Key was resolved by stripping a known group prefix (future use)."""

LOOKUP_RESOLVER_NOT_ATTEMPTED: str = "not_attempted"
"""No lookup was attempted; precondition failures prevented it."""


# ---------------------------------------------------------------------------
# HydrationResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HydrationResult:
    """
    Immutable record of a single locale key-lookup attempt.

    Produced exclusively by the canonical resolver (locale_resolver.py).
    Written to a canonical finding by the Stage 3 Hydration Orchestrator
    (not yet introduced; planned for Step 3).

    Field semantics (verbatim from Phase 4 Resolver Output Contract):

    lookup_status  — one of the LOOKUP_STATUS_* constants; never None.
    lookup_resolver — one of the LOOKUP_RESOLVER_* constants; never None.
    resolved_key   — the fully-qualified key found in the data store;
                     None for all non-RESOLVED statuses.
    current_value  — the exact translation string at resolved_key;
                     None for all non-RESOLVED statuses.
                     Empty string "" is valid (signals RESOLVED_EMPTY).
    source_hash    — SHA-256 hex of current_value for RESOLVED cases;
                     UNRESOLVED_LOOKUP_SOURCE_HASH sentinel for failure
                     cases.  Never None.
    """

    lookup_status: str
    lookup_resolver: str
    resolved_key: Optional[str]
    current_value: Optional[str]
    source_hash: str

    def is_resolved(self) -> bool:
        """Return True when a usable value was found (including empty string)."""
        return self.lookup_status in (LOOKUP_STATUS_RESOLVED, LOOKUP_STATUS_RESOLVED_EMPTY)

    def is_failed(self) -> bool:
        """Return True for any failure status (unresolved, ambiguous, missing, invalid)."""
        return self.lookup_status in (
            LOOKUP_STATUS_UNRESOLVED,
            LOOKUP_STATUS_AMBIGUOUS,
            LOOKUP_STATUS_MISSING_LOCALE,
            LOOKUP_STATUS_INVALID_KEY,
        )
