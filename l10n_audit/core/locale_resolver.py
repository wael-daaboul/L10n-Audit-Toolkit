#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
locale_resolver.py — canonical resolver shim.

Provides the canonical resolver: a thin, side-effect-free wrapper around
the existing locale_utils resolution logic that returns a typed
HydrationResult.

Public surface (stable):
  resolve(canonical_key, locale, locale_data_store) -> HydrationResult
  resolve_all(requests, locale_data_stores)          -> list[HydrationResult]

Internal helpers are prefixed with _ and are not part of the public API.

Lifecycle position: complete — stable after Step 5 cleanup.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from l10n_audit.core.audit_runtime import compute_text_hash
from l10n_audit.core.hydration_result import (
    HydrationResult,
    UNRESOLVED_LOOKUP_SOURCE_HASH,
    LOOKUP_RESOLVER_DIRECT,
    LOOKUP_RESOLVER_NOT_ATTEMPTED,
    LOOKUP_RESOLVER_SUFFIX_MATCH,
    LOOKUP_STATUS_AMBIGUOUS,
    LOOKUP_STATUS_INVALID_KEY,
    LOOKUP_STATUS_MISSING_LOCALE,
    LOOKUP_STATUS_RESOLVED,
    LOOKUP_STATUS_RESOLVED_EMPTY,
    LOOKUP_STATUS_UNRESOLVED,
)
from l10n_audit.core.locale_utils import resolve_canonical_locale_key

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

LocaleDataStore = Dict[str, object]
"""A pre-loaded mapping of fully-qualified canonical keys to translation values."""

ResolutionRequest = Tuple[str, str]
"""A (canonical_key, locale) pair for batch resolution."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_key(canonical_key: str) -> bool:
    """Return True when the key is structurally valid for lookup."""
    if not isinstance(canonical_key, str):
        return False
    return bool(canonical_key.strip())


def _build_failure(
    status: str,
    resolver: str = LOOKUP_RESOLVER_NOT_ATTEMPTED,
) -> HydrationResult:
    """Return a HydrationResult for any failure state."""
    return HydrationResult(
        lookup_status=status,
        lookup_resolver=resolver,
        resolved_key=None,
        current_value=None,
        source_hash=UNRESOLVED_LOOKUP_SOURCE_HASH,
    )


def _build_success(
    resolved_key: str,
    current_value: str,
    resolver: str,
) -> HydrationResult:
    """Return a HydrationResult for a successful lookup."""
    if current_value == "":
        status = LOOKUP_STATUS_RESOLVED_EMPTY
    else:
        status = LOOKUP_STATUS_RESOLVED
    return HydrationResult(
        lookup_status=status,
        lookup_resolver=resolver,
        resolved_key=resolved_key,
        current_value=current_value,
        source_hash=compute_text_hash(current_value),
    )


# Map from locale_utils resolution strings → LOOKUP_RESOLVER_* constants.
# This keeps the shim's terminology decoupled from locale_utils internals.
_RESOLUTION_TO_RESOLVER: Dict[str, str] = {
    "exact": LOOKUP_RESOLVER_DIRECT,
    "suffix": LOOKUP_RESOLVER_SUFFIX_MATCH,
}


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def resolve(
    canonical_key: str,
    locale: str,
    locale_data_store: Optional[LocaleDataStore],
) -> HydrationResult:
    """
    Attempt to locate canonical_key in locale_data_store and return a
    fully-populated HydrationResult.

    This function is the single source of truth for hydration output going
    forward.  At Step 2 it wraps locale_utils.resolve_canonical_locale_key
    to guarantee behavioural equivalence with the existing production path.

    Contract (verbatim from Phase 4, Section 4):
      - Never raises for data-level failures; only TypeError for wrong input types.
      - Deterministic: same inputs always produce the same HydrationResult.
      - Idempotent: multiple calls with identical arguments produce identical results.

    Decision tree (strict order):
      1. Invalid key              → INVALID_KEY  / NOT_ATTEMPTED
      2. Missing data store       → MISSING_LOCALE / NOT_ATTEMPTED
      3. Direct match non-empty   → RESOLVED      / DIRECT
      4. Direct match empty       → RESOLVED_EMPTY / DIRECT
      5. Unique suffix match      → RESOLVED[_EMPTY] / SUFFIX_MATCH
      6. Ambiguous suffix match   → AMBIGUOUS     / SUFFIX_MATCH
      7. No match                 → UNRESOLVED    / DIRECT  (attempted, failed)

    Args:
        canonical_key:      The normalized key to look up.  Must be a non-empty
                            string.  The caller (Stage 2) is responsible for
                            producing a clean canonical key before calling this.
        locale:             A single BCP-47 locale tag.  Compound values like
                            "en/ar" or meta-values like "unknown" must NOT be
                            passed; the caller must resolve them first.
        locale_data_store:  Pre-loaded mapping of fully-qualified keys to
                            translation values.  Pass None or an empty dict to
                            signal that the locale file is absent.

    Returns:
        HydrationResult with all five canonical fields populated.
    """
    # ── Precondition checks ────────────────────────────────────────────────

    # Type guard — programming error in the caller, not a data error
    if not isinstance(canonical_key, str):
        raise TypeError(
            f"canonical_key must be str, got {type(canonical_key).__name__!r}"
        )
    if not isinstance(locale, str):
        raise TypeError(
            f"locale must be str, got {type(locale).__name__!r}"
        )

    # Invalid key (structurally malformed / empty string)
    if not _validate_key(canonical_key):
        return _build_failure(LOOKUP_STATUS_INVALID_KEY)

    # Missing locale data store (None, or empty mapping treated as absent locale)
    if not locale_data_store:
        return _build_failure(LOOKUP_STATUS_MISSING_LOCALE)

    # ── Delegate to existing resolution logic ──────────────────────────────
    #
    # resolve_canonical_locale_key handles:
    #   - exact (direct) match
    #   - unique suffix match
    #   - ambiguous suffix (multiple candidates)
    #   - unresolved (no match found)
    #
    # It returns (resolved_key_or_None, resolution_string).
    resolved_key, resolution_str = resolve_canonical_locale_key(
        canonical_key, locale_data_store
    )

    # Ambiguous suffix
    if resolution_str == "ambiguous_suffix":
        return _build_failure(LOOKUP_STATUS_AMBIGUOUS, LOOKUP_RESOLVER_SUFFIX_MATCH)

    # Unresolved (no match from either direct or suffix strategies)
    if resolved_key is None:
        return _build_failure(LOOKUP_STATUS_UNRESOLVED, LOOKUP_RESOLVER_DIRECT)

    # Resolved — retrieve the raw value and normalise to str
    raw_value = locale_data_store.get(resolved_key)
    current_value: str = "" if raw_value is None else str(raw_value)

    resolver_label = _RESOLUTION_TO_RESOLVER.get(resolution_str, LOOKUP_RESOLVER_DIRECT)
    return _build_success(resolved_key, current_value, resolver_label)


def resolve_all(
    requests: Sequence[ResolutionRequest],
    locale_data_stores: Dict[str, Optional[LocaleDataStore]],
) -> List[HydrationResult]:
    """
    Apply resolve() to a sequence of (canonical_key, locale) pairs.

    Output order is guaranteed to match input order.  Failures for one entry
    do not affect others.

    Args:
        requests:           Sequence of (canonical_key, locale) pairs.
        locale_data_stores: Dict mapping locale string → pre-loaded data store.
                            If a locale is absent from the dict, all requests
                            for that locale produce MISSING_LOCALE.

    Returns:
        List of HydrationResult, one per input pair, in input order.
    """
    results: List[HydrationResult] = []
    for canonical_key, locale in requests:
        data_store = locale_data_stores.get(locale)
        results.append(resolve(canonical_key, locale, data_store))
    return results
