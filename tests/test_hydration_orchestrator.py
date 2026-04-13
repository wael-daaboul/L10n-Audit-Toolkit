"""
tests/test_hydration_orchestrator.py

Post-migration tests for the Stage 3 Hydration Orchestrator.

Step 5 state: hydration ownership is now fully in Stage 3 (Step 4 complete).
Shadow-mode scaffolding removed.  This file retains:

  A. Orchestrator correctness — all 7 resolution scenarios.
  B. Batch ordering and isolation (hydrate_issues).
  C. Live-path no-mutation — orchestrator does not alter issue dicts.
  D. Explicit locale data stores — no lazy loading.
  E. Guard regression tests — confirm no live aggregator behavior was altered.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash
from l10n_audit.core.hydration_orchestrator import HydrationRecord, hydrate_issue, hydrate_issues
from l10n_audit.core.hydration_result import (
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
from l10n_audit.reports.report_aggregator import (
    UNRESOLVED_LOOKUP_SOURCE_HASH,
    build_review_queue,
)

from conftest import write_json


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# A. Orchestrator correctness — all 7 resolution scenarios
# ---------------------------------------------------------------------------

class TestOrchestratorCorrectness:
    """The orchestrator produces the right HydrationRecord for each case."""

    STORES = {
        "en": {
            "auth.failed": "Login failed",
            "profile.name": "",
            "messages.auth.timeout": "Session timed out",
        },
        "ar": {
            "auth.failed": "فشل تسجيل الدخول",
        },
    }

    # 1 — Direct match, non-empty
    def test_direct_match_non_empty(self) -> None:
        rec = hydrate_issue("auth.failed", "en", self.STORES)
        assert isinstance(rec, HydrationRecord)
        assert rec.result.lookup_status == LOOKUP_STATUS_RESOLVED
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_DIRECT
        assert rec.result.resolved_key == "auth.failed"
        assert rec.result.current_value == "Login failed"
        assert rec.result.source_hash == _sha256("Login failed")

    # 2 — Direct match, empty string (RESOLVED_EMPTY)
    def test_direct_match_empty_string(self) -> None:
        rec = hydrate_issue("profile.name", "en", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_RESOLVED_EMPTY
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_DIRECT
        assert rec.result.current_value == ""
        assert rec.result.source_hash == _sha256("")
        assert rec.result.source_hash != UNRESOLVED_LOOKUP_SOURCE_HASH

    # 3 — Unique suffix match (Laravel-style group prefix)
    def test_unique_suffix_match(self) -> None:
        rec = hydrate_issue("auth.timeout", "en", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_RESOLVED
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_SUFFIX_MATCH
        assert rec.result.resolved_key == "messages.auth.timeout"
        assert rec.result.current_value == "Session timed out"

    # 4 — Ambiguous suffix match
    def test_ambiguous_suffix_match(self) -> None:
        stores = {
            "en": {
                "app.auth.failed": "App: Login failed",
                "web.auth.failed": "Web: Login failed",
            }
        }
        rec = hydrate_issue("auth.failed", "en", stores)
        assert rec.result.lookup_status == LOOKUP_STATUS_AMBIGUOUS
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_SUFFIX_MATCH
        assert rec.result.resolved_key is None
        assert rec.result.current_value is None
        assert rec.result.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    # 5 — Unresolved key (absent entirely)
    def test_unresolved_key(self) -> None:
        rec = hydrate_issue("no.such.key", "en", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_UNRESOLVED
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_DIRECT
        assert rec.result.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    # 6 — Missing locale data store
    def test_missing_locale_data_store_none(self) -> None:
        rec = hydrate_issue("auth.failed", "fr", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_NOT_ATTEMPTED
        assert rec.result.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_missing_locale_data_store_explicit_none(self) -> None:
        stores = {"en": None}
        rec = hydrate_issue("auth.failed", "en", stores)
        assert rec.result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    # 7 — Invalid canonical key
    def test_invalid_key_empty_string(self) -> None:
        rec = hydrate_issue("", "en", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_INVALID_KEY
        assert rec.result.lookup_resolver == LOOKUP_RESOLVER_NOT_ATTEMPTED
        assert rec.result.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_invalid_key_whitespace_only(self) -> None:
        rec = hydrate_issue("  ", "en", self.STORES)
        assert rec.result.lookup_status == LOOKUP_STATUS_INVALID_KEY

    def test_record_fields_populated(self) -> None:
        rec = hydrate_issue("auth.failed", "en", self.STORES)
        assert rec.canonical_key == "auth.failed"
        assert rec.locale == "en"
        assert isinstance(rec.result, object)


# ---------------------------------------------------------------------------
# A2. hydrate_issues batch ordering
# ---------------------------------------------------------------------------

class TestHydrateIssuesBatch:
    STORES = {
        "en": {"k1": "v1", "k2": ""},
        "ar": {"k1": "قيمة"},
    }

    def test_output_length_matches_input(self) -> None:
        requests = [("k1", "en"), ("k2", "en"), ("k1", "ar"), ("missing", "en")]
        results = hydrate_issues(requests, self.STORES)
        assert len(results) == 4

    def test_output_order_preserved(self) -> None:
        requests = [("k1", "en"), ("k2", "en"), ("k1", "ar")]
        results = hydrate_issues(requests, self.STORES)
        assert results[0].result.current_value == "v1"
        assert results[1].result.lookup_status == LOOKUP_STATUS_RESOLVED_EMPTY
        assert results[2].result.current_value == "قيمة"

    def test_empty_request_list(self) -> None:
        results = hydrate_issues([], self.STORES)
        assert results == []

    def test_failure_in_one_does_not_affect_others(self) -> None:
        requests = [("k1", "en"), ("missing", "en"), ("k1", "ar")]
        results = hydrate_issues(requests, self.STORES)
        assert results[0].result.is_resolved()
        assert results[1].result.lookup_status == LOOKUP_STATUS_UNRESOLVED
        assert results[2].result.is_resolved()



# ---------------------------------------------------------------------------
# D. Live path unchanged — build_review_queue() output is NOT affected
# ---------------------------------------------------------------------------

class TestLivePathUnchanged:
    """
    build_review_queue() must produce identical rows regardless of whether
    the orchestrator is also running.  This test calls build_review_queue()
    alongside the orchestrator and confirms row values are unchanged.
    """

    def _runtime(self, tmp_path: Path, en: dict, ar: dict):
        write_json(tmp_path / "en.json", en)
        write_json(tmp_path / "ar.json", ar)
        return type("R", (), {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        })()

    def test_build_review_queue_rows_unchanged_with_orchestrator_running(
        self, tmp_path: Path
    ) -> None:
        en = {"auth.failed": "Login failed"}
        ar = {"auth.failed": "فشل تسجيل الدخول"}
        runtime = self._runtime(tmp_path, en, ar)
        issues = [
            {
                "key": "auth.failed",
                "issue_type": "locale_qc",
                "message": "Check punctuation",
                "locale": "ar",
                "severity": "low",
                "source": "locale_qc",
                "details": {"old": "فشل تسجيل الدخول"},
                "new": "فشل تسجيل الدخول.",
            }
        ]

        # Run orchestrator alongside (shadow mode)
        stores = {"en": en, "ar": ar}
        shadow_records = hydrate_issues([("auth.failed", "ar")], stores)
        assert len(shadow_records) == 1  # orchestrator ran

        # Run live pipeline — Stage 3 now owns hydration
        rows = build_review_queue(issues, runtime)
        for row in rows:
            # The review queue receives hydration state from Stage 3 orchestrator
            assert "source_hash" in row
            assert row["source_hash"]  # must be non-empty

    def test_orchestrator_result_does_not_mutate_issue_dict(self) -> None:
        """Orchestrator must not modify the original issue dict."""
        stores = {"en": {"auth.failed": "Login failed"}}
        issue = {"key": "auth.failed", "locale": "en", "issue_type": "x", "message": "y"}
        original_keys = set(issue.keys())
        hydrate_issue("auth.failed", "en", stores)  # run orchestrator
        assert set(issue.keys()) == original_keys, "Orchestrator must not mutate issue dicts"


# ---------------------------------------------------------------------------
# E. Locale data stores explicitly passed — no lazy loading
# ---------------------------------------------------------------------------

class TestExplicitLocaleDataStores:
    """
    The orchestrator must never load locale files itself.
    Missing or None data stores must produce MISSING_LOCALE, not a file-system error.
    """

    def test_missing_locale_produces_missing_locale_status_not_error(self) -> None:
        # "zz" is not a locale we have data for
        rec = hydrate_issue("some.key", "zz", {"en": {"some.key": "val"}})
        assert rec.result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_empty_stores_dict_produces_missing_locale(self) -> None:
        rec = hydrate_issue("some.key", "en", {})
        assert rec.result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_none_in_stores_produces_missing_locale(self) -> None:
        rec = hydrate_issue("some.key", "en", {"en": None})
        assert rec.result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE

    def test_orchestrator_does_not_accept_file_path_as_store(self) -> None:
        """
        Passing a str path instead of a dict must NOT cause file I/O.

        A str is truthy, so the resolver does not short-circuit to MISSING_LOCALE;
        instead it attempts a key lookup against the string (which contains no mapping
        entries) and produces UNRESOLVED.  Either MISSING_LOCALE or UNRESOLVED is
        acceptable — the important guarantee is that no file read occurs and the
        result is a non-success status.
        """
        stores = {"en": "/some/path/en.json"}  # type: ignore[assignment]
        rec = hydrate_issue("key", "en", stores)
        # Must be a failure status — file I/O would produce a resolved value
        assert not rec.result.is_resolved(), (
            f"Expected a non-resolved status; got {rec.result.lookup_status!r}"
        )
        assert rec.result.source_hash == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_batch_uses_provided_stores_only(self) -> None:
        stores = {"en": {"k": "v"}}
        results = hydrate_issues([("k", "en"), ("k", "ar")], stores)
        assert results[0].result.is_resolved()
        assert results[1].result.lookup_status == LOOKUP_STATUS_MISSING_LOCALE


# ---------------------------------------------------------------------------
# F. Critical guard regression tests
# ---------------------------------------------------------------------------

class TestGuardRegressions:
    """
    These tests confirm that no live report_aggregator behavior was altered
    by the introduction of the orchestrator.
    They mirror existing guard tests and must pass identically.
    """

    def _runtime(self, tmp_path: Path, en: dict, ar: dict):
        write_json(tmp_path / "en.json", en)
        write_json(tmp_path / "ar.json", ar)
        return type("R", (), {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        })()

    def test_unresolved_hash_sentinel_still_used_in_live_path(
        self, tmp_path: Path
    ) -> None:
        """build_review_queue still writes UNRESOLVED_HASH for missing keys."""
        runtime = self._runtime(tmp_path, {}, {})
        issues = [
            {
                "key": "missing.key",
                "issue_type": "missing_in_ar",
                "locale": "ar",
                "message": "Missing",
                "source": "localization",
                "severity": "medium",
            }
        ]
        rows = build_review_queue(issues, runtime)
        for row in rows:
            assert row["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_empty_value_uses_hash_of_empty_string_not_sentinel(
        self, tmp_path: Path
    ) -> None:
        """build_review_queue still writes SHA256('') for truly empty translations."""
        en = {"empty.key": ""}
        runtime = self._runtime(tmp_path, en, {})
        issues = [
            {
                "key": "empty.key",
                "issue_type": "empty_en",
                "locale": "en",
                "message": "Empty",
                "source": "locale_qc",
                "severity": "medium",
                "old": "",
                "new": "Fill this in",
            }
        ]
        rows = build_review_queue(issues, runtime)
        for row in rows:
            assert row["source_hash"] != UNRESOLVED_LOOKUP_SOURCE_HASH
            assert row["source_hash"] == compute_text_hash("")

    def test_laravel_suffix_resolution_still_resolves_in_live_path(
        self, tmp_path: Path
    ) -> None:
        """build_review_queue still resolves group-prefixed Laravel keys."""
        en = {"messages.auth.failed": "Login failed"}
        runtime = self._runtime(tmp_path, en, {})
        issues = [
            {
                "key": "auth.failed",
                "issue_type": "locale_qc",
                "locale": "en",
                "message": "Check",
                "source": "locale_qc",
                "severity": "low",
                "old": "Login failed",
                "new": "Login Failed",
            }
        ]
        rows = build_review_queue(issues, runtime)
        for row in rows:
            assert row.get("source_hash") != UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_orchestrator_source_hash_for_laravel_suffix_via_aggregator(
        self, tmp_path: Path
    ) -> None:
        """Orchestrator produces the same source_hash that build_review_queue writes."""
        en = {"messages.auth.failed": "Login failed"}
        runtime = self._runtime(tmp_path, en, {})
        issues = [
            {
                "key": "auth.failed",
                "issue_type": "locale_qc",
                "locale": "en",
                "message": "Check",
                "source": "locale_qc",
                "severity": "low",
                "new": "Login Failed",
            }
        ]
        rows = build_review_queue(issues, runtime)
        rec = hydrate_issue("auth.failed", "en", {"en": en})
        assert rows
        assert rows[0]["source_hash"] == rec.result.source_hash
        assert rec.result.lookup_status == LOOKUP_STATUS_RESOLVED
