#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hydration_orchestrator.py — Stage 3 Hydration Orchestrator.

This is the LIVE hydration owner as of Step 4 of the migration plan.
build_review_queue() calls hydrate_issue() here for every finding.

Responsibilities (strictly bounded):
  - Accept pre-loaded locale data stores (no file I/O).
  - Accept pre-resolved (canonical_key, locale) pairs — no locale inference.
  - Call the resolver for each pair.
  - Return HydrationRecord objects.

Must NOT:
  - Perform locale inference.
  - Perform candidate extraction or suggestion.
  - Access workflow state, workbook columns, or projection fields.
  - Compute candidate_hash or approved_value.
  - Load locale files itself.

Lifecycle position: complete — live owner after Step 5 cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from l10n_audit.core.hydration_result import HydrationResult
from l10n_audit.core.locale_resolver import LocaleDataStore, resolve


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HydrationRecord:
    """
    The result of a single orchestrated hydration attempt.

    canonical_key  — the key that was passed to the resolver (may differ from
                     resolved_key if suffix matching was used).
    locale         — the single BCP-47 locale tag used for the lookup.
    result         — the full HydrationResult from the resolver.
    """
    canonical_key: str
    locale: str
    result: HydrationResult


# ---------------------------------------------------------------------------
# Core orchestration API
# ---------------------------------------------------------------------------

def hydrate_issue(
    canonical_key: str,
    locale: str,
    locale_data_stores: Dict[str, Optional[LocaleDataStore]],
) -> HydrationRecord:
    """
    Hydrate a single (canonical_key, locale) pair against the provided data stores.

    Args:
        canonical_key:       The normalised key to look up.
        locale:              A single, already-resolved BCP-47 locale tag.
                             Must NOT be a compound value or "unknown".
        locale_data_stores:  Dict mapping locale → pre-loaded key-value mapping.
                             The orchestrator selects the correct store; it does
                             not load files itself.

    Returns:
        HydrationRecord containing all five canonical hydration fields.
    """
    data_store = locale_data_stores.get(locale)
    result = resolve(canonical_key, locale, data_store)
    return HydrationRecord(canonical_key=canonical_key, locale=locale, result=result)


def hydrate_issues(
    requests: Sequence[Tuple[str, str]],
    locale_data_stores: Dict[str, Optional[LocaleDataStore]],
) -> List[HydrationRecord]:
    """
    Hydrate a batch of (canonical_key, locale) pairs.

    Output order is guaranteed to match input order.  A failure for one
    entry does not affect others.

    Args:
        requests:            Sequence of (canonical_key, locale) pairs.
                             Locale must already be resolved to a single
                             BCP-47 tag before calling this function.
        locale_data_stores:  Dict mapping locale → pre-loaded key-value mapping.
                             If a locale is absent from the dict, all requests
                             for that locale produce MISSING_LOCALE.

    Returns:
        A list of HydrationRecord, one per input pair, in input order.
    """
    return [
        hydrate_issue(canonical_key, locale, locale_data_stores)
        for canonical_key, locale in requests
    ]
