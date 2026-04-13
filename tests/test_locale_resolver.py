"""
tests/test_locale_resolver.py

Behavioural equivalence and correctness tests for the Step 2 resolver shim
(l10n_audit.core.locale_resolver).

Coverage targets (from Phase 5, Step 2 Checkpoint Gate):
  1. Direct match — non-empty value
  2. Direct match — empty string value  (RESOLVED_EMPTY, not UNRESOLVED)
  3. Unique suffix match                (Laravel-style group-prefixed key)
  4. Ambiguous suffix match             (two or more candidates → AMBIGUOUS)
  5. Unresolved key                     (key absent entirely)
  6. Missing locale data store          (None / empty dict → MISSING_LOCALE)
  7. Invalid key                        (empty string / whitespace-only)

Additionally verifies:
  - UNRESOLVED_HASH sentinel is used for all failure paths
  - SHA256("") is used for RESOLVED_EMPTY (distinct from UNRESOLVED_HASH)
  - resolve_all preserves input order and isolates failures
  - TypeError is raised for non-string canonical_key / locale
  - All HydrationResult fields are always populated (no None source_hash)
"""
from __future__ import annotations

import hashlib
import pytest

from l10n_audit.core.hydration_result import (
    HydrationResult,
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
from l10n_audit.core.locale_resolver import resolve, resolve_all
from l10n_audit.reports.report_aggregator import UNRESOLVED_LOOKUP_SOURCE_HASH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Case 1 — Direct match, non-empty value
# ---------------------------------------------------------------------------

class TestDirectMatchNonEmpty:
    DATA = {"auth.failed": "Invalid credentials"}

    def test_lookup_status_resolved(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_RESOLVED

    def test_lookup_resolver_direct(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_DIRECT

    def test_resolved_key_equals_canonical(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.resolved_key == "auth.failed"

    def test_current_value_is_stored_string(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.current_value == "Invalid credentials"

    def test_source_hash_is_sha256_of_value(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.source_hash == _sha256("Invalid credentials")

    def test_source_hash_is_not_sentinel(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.source_hash != UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_is_resolved_helper(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.is_resolved() is True
        assert r.is_failed() is False


# ---------------------------------------------------------------------------
# Case 2 — Direct match, empty string value  (RESOLVED_EMPTY)
# ---------------------------------------------------------------------------

class TestDirectMatchEmptyString:
    DATA = {"profile.name": ""}

    def test_lookup_status_resolved_empty(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_RESOLVED_EMPTY

    def test_lookup_resolver_direct(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_DIRECT

    def test_resolved_key_is_set(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.resolved_key == "profile.name"

    def test_current_value_is_empty_string(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.current_value == ""

    def test_source_hash_is_sha256_of_empty_string(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.source_hash == _sha256("")

    def test_empty_hash_is_NOT_sentinel(self) -> None:
        """
        Critical invariant: SHA256("") must be distinct from UNRESOLVED_HASH.
        A key with an empty translation is RESOLVED_EMPTY, not UNRESOLVED.
        """
        r = resolve("profile.name", "en", self.DATA)
        assert r.source_hash != UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_is_resolved_returns_true_for_resolved_empty(self) -> None:
        r = resolve("profile.name", "en", self.DATA)
        assert r.is_resolved() is True


# ---------------------------------------------------------------------------
# Case 3 — Unique suffix match  (Laravel group-prefixed key resolution)
# ---------------------------------------------------------------------------

class TestUniqueSuffixMatch:
    DATA = {
        "messages.auth.failed": "Invalid credentials",
        "messages.auth.success": "Login successful",
    }

    def test_short_key_resolves_via_suffix(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_RESOLVED

    def test_lookup_resolver_suffix_match(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_SUFFIX_MATCH

    def test_resolved_key_is_prefixed_form(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.resolved_key == "messages.auth.failed"

    def test_current_value_from_prefixed_key(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.current_value == "Invalid credentials"

    def test_source_hash_of_resolved_value(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.source_hash == _sha256("Invalid credentials")

    def test_direct_full_key_still_works(self) -> None:
        """Verbatim key should work as a direct match too."""
        r = resolve("messages.auth.failed", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_RESOLVED
        assert r.lookup_resolver == LOOKUP_RESOLVER_DIRECT


# ---------------------------------------------------------------------------
# Case 4 — Ambiguous suffix match
# ---------------------------------------------------------------------------

class TestAmbiguousSuffixMatch:
    DATA = {
        "app.auth.failed": "Failed (app)",
        "web.auth.failed": "Failed (web)",
    }

    def test_lookup_status_ambiguous(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_AMBIGUOUS

    def test_lookup_resolver_suffix_match(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_SUFFIX_MATCH

    def test_resolved_key_is_none(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.resolved_key is None

    def test_current_value_is_none(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.current_value is None

    def test_source_hash_is_sentinel(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_is_failed(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.is_failed() is True
        assert r.is_resolved() is False


# ---------------------------------------------------------------------------
# Case 5 — Unresolved key (key absent entirely)
# ---------------------------------------------------------------------------

class TestUnresolvedKey:
    DATA = {"other.key": "Some value"}

    def test_lookup_status_unresolved(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_UNRESOLVED

    def test_lookup_resolver_direct_attempted(self) -> None:
        """Resolver attempted direct lookup and failed; reports DIRECT."""
        r = resolve("auth.failed", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_DIRECT

    def test_resolved_key_is_none(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.resolved_key is None

    def test_current_value_is_none(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.current_value is None

    def test_source_hash_is_sentinel(self) -> None:
        r = resolve("auth.failed", "en", self.DATA)
        assert r.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_sentinel_differs_from_empty_string_hash(self) -> None:
        """
        Guard: UNRESOLVED (key missing) must produce a different source_hash
        than RESOLVED_EMPTY (key present with empty value).
        """
        unresolved = resolve("auth.failed", "en", self.DATA)
        resolved_empty = resolve("auth.failed", "en", {"auth.failed": ""})
        assert unresolved.source_hash != resolved_empty.source_hash


# ---------------------------------------------------------------------------
# Case 6 — Missing locale data store
# ---------------------------------------------------------------------------

class TestMissingLocaleDataStore:

    def test_none_data_store_gives_missing_locale(self) -> None:
        r = resolve("any.key", "ar", None)
        assert r.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_empty_dict_gives_missing_locale(self) -> None:
        r = resolve("any.key", "ar", {})
        assert r.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_lookup_resolver_not_attempted(self) -> None:
        r = resolve("any.key", "ar", None)
        assert r.lookup_resolver == LOOKUP_RESOLVER_NOT_ATTEMPTED

    def test_resolved_key_is_none(self) -> None:
        r = resolve("any.key", "ar", None)
        assert r.resolved_key is None

    def test_current_value_is_none(self) -> None:
        r = resolve("any.key", "ar", None)
        assert r.current_value is None

    def test_source_hash_is_sentinel(self) -> None:
        r = resolve("any.key", "ar", None)
        assert r.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH


# ---------------------------------------------------------------------------
# Case 7 — Invalid / malformed canonical key
# ---------------------------------------------------------------------------

class TestInvalidKey:
    DATA = {"some.key": "value"}

    def test_empty_string_key(self) -> None:
        r = resolve("", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_INVALID_KEY

    def test_whitespace_only_key(self) -> None:
        r = resolve("   ", "en", self.DATA)
        assert r.lookup_status == LOOKUP_STATUS_INVALID_KEY

    def test_lookup_resolver_not_attempted_for_invalid(self) -> None:
        r = resolve("", "en", self.DATA)
        assert r.lookup_resolver == LOOKUP_RESOLVER_NOT_ATTEMPTED

    def test_resolved_key_none_for_invalid(self) -> None:
        r = resolve("", "en", self.DATA)
        assert r.resolved_key is None

    def test_source_hash_is_sentinel_for_invalid(self) -> None:
        r = resolve("", "en", self.DATA)
        assert r.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_non_string_key_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            resolve(42, "en", self.DATA)  # type: ignore[arg-type]

    def test_non_string_locale_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            resolve("some.key", 123, self.DATA)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HydrationResult invariants
# ---------------------------------------------------------------------------

class TestHydrationResultInvariants:
    """source_hash must always be a non-None string across all result types."""

    def _all_results(self):
        data = {"messages.auth.failed": "Login failed", "profile": ""}
        ambiguous_data = {"a.auth.failed": "x", "b.auth.failed": "y"}
        return [
            resolve("messages.auth.failed", "en", data),        # RESOLVED
            resolve("profile", "en", data),                     # RESOLVED_EMPTY
            resolve("auth.failed", "en", ambiguous_data),       # AMBIGUOUS
            resolve("missing.key", "en", data),                 # UNRESOLVED
            resolve("any.key", "en", None),                     # MISSING_LOCALE
            resolve("", "en", data),                            # INVALID_KEY
        ]

    def test_source_hash_never_none(self) -> None:
        for result in self._all_results():
            assert result.source_hash is not None, (
                f"source_hash must not be None for status={result.lookup_status!r}"
            )

    def test_lookup_status_never_none(self) -> None:
        for result in self._all_results():
            assert result.lookup_status is not None

    def test_lookup_resolver_never_none(self) -> None:
        for result in self._all_results():
            assert result.lookup_resolver is not None

    def test_resolved_key_null_iff_not_resolved(self) -> None:
        for result in self._all_results():
            if result.is_resolved():
                assert result.resolved_key is not None, (
                    f"resolved_key must be set when status={result.lookup_status!r}"
                )
            else:
                assert result.resolved_key is None, (
                    f"resolved_key must be None when status={result.lookup_status!r}"
                )

    def test_current_value_null_iff_not_resolved(self) -> None:
        for result in self._all_results():
            if result.is_resolved():
                assert result.current_value is not None, (
                    f"current_value must be set when status={result.lookup_status!r}"
                )
            else:
                assert result.current_value is None, (
                    f"current_value must be None when status={result.lookup_status!r}"
                )

    def test_result_is_frozen(self) -> None:
        r = resolve("messages.auth.failed", "en", {"messages.auth.failed": "val"})
        with pytest.raises((AttributeError, TypeError)):
            r.source_hash = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# resolve_all — batch ordering and isolation
# ---------------------------------------------------------------------------

class TestResolveAll:
    DATA_STORES = {
        "en": {"auth.failed": "Login failed", "profile": ""},
        "ar": {"auth.failed": "فشل تسجيل الدخول"},
    }

    def test_output_length_matches_input(self) -> None:
        requests = [
            ("auth.failed", "en"),
            ("profile", "en"),
            ("auth.failed", "ar"),
            ("missing.key", "en"),
        ]
        results = resolve_all(requests, self.DATA_STORES)
        assert len(results) == len(requests)

    def test_output_order_preserved(self) -> None:
        requests = [
            ("auth.failed", "en"),
            ("profile", "en"),
            ("auth.failed", "ar"),
        ]
        results = resolve_all(requests, self.DATA_STORES)
        assert results[0].lookup_status == LOOKUP_STATUS_RESOLVED
        assert results[0].current_value == "Login failed"
        assert results[1].lookup_status == LOOKUP_STATUS_RESOLVED_EMPTY
        assert results[1].current_value == ""
        assert results[2].lookup_status == LOOKUP_STATUS_RESOLVED
        assert results[2].current_value == "فشل تسجيل الدخول"

    def test_failure_in_one_does_not_affect_others(self) -> None:
        requests = [
            ("auth.failed", "en"),    # should resolve
            ("missing.key", "en"),    # should fail
            ("auth.failed", "ar"),    # should resolve
        ]
        results = resolve_all(requests, self.DATA_STORES)
        assert results[0].is_resolved()
        assert results[1].lookup_status == LOOKUP_STATUS_UNRESOLVED
        assert results[2].is_resolved()

    def test_missing_locale_in_stores(self) -> None:
        requests = [("auth.failed", "fr")]  # "fr" not in DATA_STORES
        results = resolve_all(requests, self.DATA_STORES)
        assert results[0].lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_empty_request_list(self) -> None:
        results = resolve_all([], self.DATA_STORES)
        assert results == []


# ---------------------------------------------------------------------------
# Determinism and idempotency
# ---------------------------------------------------------------------------

class TestDeterminismAndIdempotency:
    DATA = {"auth.failed": "Login failed"}

    def test_same_inputs_produce_same_result(self) -> None:
        r1 = resolve("auth.failed", "en", self.DATA)
        r2 = resolve("auth.failed", "en", self.DATA)
        assert r1 == r2

    def test_different_values_produce_different_hashes(self) -> None:
        data_a = {"auth.failed": "Login failed"}
        data_b = {"auth.failed": "Authentication error"}
        r_a = resolve("auth.failed", "en", data_a)
        r_b = resolve("auth.failed", "en", data_b)
        assert r_a.source_hash != r_b.source_hash
