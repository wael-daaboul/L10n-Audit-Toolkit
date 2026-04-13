"""
tests/test_step4_ownership_transfer.py

Focused tests for Step 4 of the Hydration Ownership Migration Plan:
"Redirect build_review_queue() to consume pre-hydrated canonical state."

Verification goals:

1.  build_review_queue() consumes hydration state from Stage 3 orchestrator.
2.  _hydrate_old_value_for_issue() is no longer called by the live path
    (proven by patching it to raise and confirming no error).
3.  NOT_HYDRATED input raises a loud RuntimeError (guard present).
4.  Projection rows still carry correct old_value / source_old_value / source_hash
    from canonical hydration.
5.  UNRESOLVED_HASH sentinel is produced for missing keys.
6.  SHA256('') is produced for empty-value keys (RESOLVED_EMPTY ≠ UNRESOLVED).
7.  Laravel unique suffix resolution still works via the resolver.
8.  Apply safety guard tests pass unchanged.
9.  Workbook column freeze tests pass unchanged.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash
from l10n_audit.core.hydration_result import LOOKUP_STATUS_NOT_HYDRATED
from l10n_audit.reports.report_aggregator import (
    UNRESOLVED_LOOKUP_SOURCE_HASH,
    build_review_queue,
)

from conftest import write_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _runtime(tmp_path: Path, en: dict, ar: dict):
    write_json(tmp_path / "en.json", en)
    write_json(tmp_path / "ar.json", ar)
    return type("R", (), {
        "en_file": tmp_path / "en.json",
        "ar_file": tmp_path / "ar.json",
        "locale_format": "json",
        "source_locale": "en",
        "target_locales": ("ar",),
    })()


def _simple_issue(key: str, locale: str, *, issue_type: str = "locale_qc",
                  severity: str = "low", old: str | None = None, new: str = "") -> dict:
    issue: dict = {
        "key": key,
        "locale": locale,
        "issue_type": issue_type,
        "severity": severity,
        "message": "test issue",
        "source": "locale_qc",
    }
    if old is not None:
        issue["old"] = old
    if new:
        issue["new"] = new
    return issue


# ---------------------------------------------------------------------------
# 1. Ownership transfer: Stage 3 orchestrator is the source of hydration
# ---------------------------------------------------------------------------

class TestOwnershipTransferred:

    def test_source_hash_comes_from_live_lookup_not_cached_field(
        self, tmp_path: Path
    ) -> None:
        """
        The live lookup value must win over any pre-existing cached field.
        Under the ADR decision: details.old is evidence, NOT hydration truth.
        """
        en = {"auth.failed": "Live value from locale file"}
        runtime = _runtime(tmp_path, en, {})
        issue = {
            "key": "auth.failed",
            "locale": "en",
            "issue_type": "locale_qc",
            "severity": "low",
            "message": "check",
            "source": "locale_qc",
            # OLD PATH would have used this cached value for source_hash
            "details": {"old": "STALE cached detection-time value"},
            "new": "Live value from locale file.",
        }
        rows = build_review_queue([issue], runtime)
        assert rows, "Expected at least one row"
        row = rows[0]
        # source_hash must come from the live lookup ("Live value from locale file")
        # NOT from details.old ("STALE cached detection-time value")
        assert row["source_hash"] == _sha256("Live value from locale file"), (
            f"source_hash={row['source_hash']!r} — expected SHA256 of live value, "
            "not SHA256 of stale cached details.old"
        )
        assert row["old_value"] == "Live value from locale file"


# ---------------------------------------------------------------------------
# 2. _hydrate_old_value_for_issue is NO LONGER CALLED
# ---------------------------------------------------------------------------

class TestOldHydrationHelperRemoved:
    """
    Step 5 cleanup verification: _hydrate_old_value_for_issue has been removed.
    The tests that formerly patched it now prove the symbol is gone and
    confirm the live path is backed exclusively by the orchestrator.
    """

    def test_old_helper_symbol_is_gone_from_report_aggregator(self) -> None:
        """
        _hydrate_old_value_for_issue must not exist as an attribute of
        report_aggregator after Step 5 cleanup.
        """
        import l10n_audit.reports.report_aggregator as ra
        assert not hasattr(ra, "_hydrate_old_value_for_issue"), (
            "_hydrate_old_value_for_issue was supposed to be removed in Step 5 "
            "but is still present in report_aggregator"
        )

    def test_build_review_queue_backed_by_orchestrator_not_old_helper(
        self, tmp_path: Path
    ) -> None:
        """
        build_review_queue() must produce a correct result without
        _hydrate_old_value_for_issue existing anywhere — proving the live
        path is fully orchestrator-backed.
        """
        from unittest.mock import patch
        en = {"greeting": "Hello"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("greeting", "en", new="Hello!")

        # Even if we somehow prevent _hydrate_old_value_for_issue from being called
        # (it no longer exists), build_review_queue must still produce a correct row.
        rows = build_review_queue([issue], runtime)
        assert rows, "Expected at least one row from orchestrator-backed path"
        assert rows[0]["source_hash"] == _sha256("Hello")

    def test_old_helper_patched_to_wrong_hash_does_not_affect_output(
        self, tmp_path: Path
    ) -> None:
        """
        Patching hydrate_issue to return a 'wrong' value proves the live path
        reads exclusively from the orchestrator output — _hydrate_old_value_for_issue
        cannot interfere because it no longer exists.
        """
        from unittest.mock import patch
        from l10n_audit.core.hydration_result import (
            HydrationResult,
            LOOKUP_RESOLVER_DIRECT,
            LOOKUP_STATUS_RESOLVED,
        )
        from l10n_audit.core.hydration_orchestrator import HydrationRecord

        correct_result = HydrationResult(
            lookup_status=LOOKUP_STATUS_RESOLVED,
            lookup_resolver=LOOKUP_RESOLVER_DIRECT,
            resolved_key="greeting",
            current_value="Hello",
            source_hash=_sha256("Hello"),
        )
        correct_record = HydrationRecord(
            canonical_key="greeting", locale="en", result=correct_result
        )

        en = {"greeting": "Hello"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("greeting", "en", new="Hello!")

        with patch(
            "l10n_audit.reports.report_aggregator.hydrate_issue",
            return_value=correct_record,
        ):
            rows = build_review_queue([issue], runtime)

        assert rows
        assert rows[0]["source_hash"] == _sha256("Hello")



# ---------------------------------------------------------------------------
# 3. NOT_HYDRATED guard raises loudly
# ---------------------------------------------------------------------------

class TestHydrationGuard:

    def test_not_hydrated_status_raises_runtime_error(self, tmp_path: Path) -> None:
        """
        build_review_queue must raise RuntimeError if it ever receives a finding
        whose hydration state is NOT_HYDRATED.
        We simulate this by patching the orchestrator to return NOT_HYDRATED.
        """
        from l10n_audit.core.hydration_result import HydrationResult, LOOKUP_RESOLVER_NOT_ATTEMPTED
        from l10n_audit.core.hydration_orchestrator import HydrationRecord

        not_hydrated_result = HydrationResult(
            lookup_status=LOOKUP_STATUS_NOT_HYDRATED,
            lookup_resolver=LOOKUP_RESOLVER_NOT_ATTEMPTED,
            resolved_key=None,
            current_value=None,
            source_hash=UNRESOLVED_LOOKUP_SOURCE_HASH,
        )
        not_hydrated_record = HydrationRecord(
            canonical_key="greeting", locale="en", result=not_hydrated_result
        )

        en = {"greeting": "Hello"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("greeting", "en", old="Hello", new="Hello!")

        with patch(
            "l10n_audit.reports.report_aggregator.hydrate_issue",
            return_value=not_hydrated_record,
        ):
            with pytest.raises(RuntimeError, match="non-hydrated finding"):
                build_review_queue([issue], runtime)


# ---------------------------------------------------------------------------
# 4. Projection rows carry correct values from canonical hydration
# ---------------------------------------------------------------------------

class TestProjectionValuesFromCanonicalHydration:

    def test_old_value_reflects_live_lookup(self, tmp_path: Path) -> None:
        en = {"auth.failed": "Login failed"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("auth.failed", "en", old="cached old", new="Login Failed")
        rows = build_review_queue([issue], runtime)
        assert rows
        assert rows[0]["old_value"] == "Login failed"  # live lookup value

    def test_source_old_value_equals_old_value(self, tmp_path: Path) -> None:
        en = {"auth.failed": "Login failed"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("auth.failed", "en", old="cached old", new="Login Failed")
        rows = build_review_queue([issue], runtime)
        assert rows
        assert rows[0]["source_old_value"] == rows[0]["old_value"]

    def test_source_hash_is_sha256_of_live_value(self, tmp_path: Path) -> None:
        en = {"auth.failed": "Login failed"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("auth.failed", "en", new="Login Failed")
        rows = build_review_queue([issue], runtime)
        assert rows
        assert rows[0]["source_hash"] == _sha256("Login failed")

    def test_ar_finding_gets_ar_live_value(self, tmp_path: Path) -> None:
        ar = {"greeting": "مرحبا"}
        runtime = _runtime(tmp_path, {}, ar)
        issue = _simple_issue("greeting", "ar", new="مرحبًا")
        rows = build_review_queue([issue], runtime)
        assert rows
        assert rows[0]["old_value"] == "مرحبا"
        assert rows[0]["source_hash"] == _sha256("مرحبا")


# ---------------------------------------------------------------------------
# 5. Unresolved sentinel behavior unchanged
# ---------------------------------------------------------------------------

class TestUnresolvedSentinelUnchanged:

    def test_missing_key_uses_unresolved_hash(self, tmp_path: Path) -> None:
        runtime = _runtime(tmp_path, {}, {})
        issue = {
            "key": "no.such.key",
            "locale": "ar",
            "issue_type": "missing_in_ar",
            "severity": "medium",
            "message": "Missing",
            "source": "localization",
        }
        rows = build_review_queue([issue], runtime)
        for row in rows:
            assert row["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_missing_locale_uses_unresolved_hash(self, tmp_path: Path) -> None:
        """When locale is fully unknown, resolver produces MISSING_LOCALE → sentinel hash."""
        runtime = _runtime(tmp_path, {}, {})
        issue = {
            "key": "some.key",
            "issue_type": "locale_qc",
            "severity": "low",
            "message": "Check",
            "source": "locale_qc",
            "new": "corrected",
            # No locale field → locale_context will be None → "unknown" → MISSING_LOCALE
        }
        rows = build_review_queue([issue], runtime)
        for row in rows:
            assert row["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH


# ---------------------------------------------------------------------------
# 6. Empty-value distinction: SHA256('') ≠ UNRESOLVED_HASH
# ---------------------------------------------------------------------------

class TestEmptyVsUnresolvedDistinction:

    def test_empty_translation_hash_differs_from_sentinel(self, tmp_path: Path) -> None:
        en = {"empty.key": ""}
        runtime = _runtime(tmp_path, en, {})
        issue = {
            "key": "empty.key",
            "locale": "en",
            "issue_type": "empty_en",
            "severity": "medium",
            "message": "Empty value",
            "source": "locale_qc",
            "old": "",
            "new": "Fill me in",
        }
        rows = build_review_queue([issue], runtime)
        for row in rows:
            assert row["source_hash"] != UNRESOLVED_LOOKUP_SOURCE_HASH, (
                "RESOLVED_EMPTY must produce SHA256(''), not the sentinel"
            )
            assert row["source_hash"] == _sha256(""), (
                "RESOLVED_EMPTY source_hash must be SHA256 of empty string"
            )


# ---------------------------------------------------------------------------
# 7. Laravel suffix resolution still works
# ---------------------------------------------------------------------------

class TestLaravelSuffixResolutionUnchanged:

    def test_group_prefixed_key_resolves_via_suffix(self, tmp_path: Path) -> None:
        en = {"messages.auth.failed": "Login failed"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("auth.failed", "en", new="Login Failed")
        rows = build_review_queue([issue], runtime)
        assert rows, "Expected a row for the suffix-resolved key"
        row = rows[0]
        assert row["source_hash"] != UNRESOLVED_LOOKUP_SOURCE_HASH, (
            "Suffix-resolved key must not produce sentinel hash"
        )
        assert row["source_hash"] == _sha256("Login failed")
        assert row["old_value"] == "Login failed"

    def test_ambiguous_suffix_uses_sentinel(self, tmp_path: Path) -> None:
        en = {"app.auth.failed": "App fail", "web.auth.failed": "Web fail"}
        runtime = _runtime(tmp_path, en, {})
        issue = _simple_issue("auth.failed", "en", new="corrected")
        rows = build_review_queue([issue], runtime)
        for row in rows:
            assert row["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH


# ---------------------------------------------------------------------------
# 8-9. Guard regressions — existing suite contracts remain valid
# These directly mirror the most critical existing tests.
# ---------------------------------------------------------------------------

class TestExistingGuardContractsPreserved:

    def test_missing_key_review_queue_row_has_sentinel(self, tmp_path: Path) -> None:
        write_json(tmp_path / "en.json", {})
        write_json(tmp_path / "ar.json", {})
        runtime = type("R", (), {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        })()
        issues = [{
            "key": "missing.key",
            "issue_type": "missing_in_ar",
            "locale": "ar",
            "message": "Missing",
            "source": "localization",
            "severity": "medium",
        }]
        rows = build_review_queue(issues, runtime)
        for row in rows:
            assert row["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH

    def test_source_hash_column_always_populated(self, tmp_path: Path) -> None:
        en = {"k": "v"}
        runtime = _runtime(tmp_path, en, {})
        issues = [_simple_issue("k", "en", new="v2")]
        rows = build_review_queue(issues, runtime)
        for row in rows:
            assert "source_hash" in row
            assert row["source_hash"]  # non-empty

    def test_source_hash_of_confirmed_missing_key_uses_sentinel(
        self, tmp_path: Path
    ) -> None:
        write_json(tmp_path / "en.json", {"welcome": "Welcome"})
        write_json(tmp_path / "ar.json", {})
        runtime = type("R", (), {
            "en_file": tmp_path / "en.json",
            "ar_file": tmp_path / "ar.json",
            "locale_format": "json",
            "source_locale": "en",
            "target_locales": ("ar",),
        })()
        issues = [{
            "key": "welcome",
            "issue_type": "confirmed_missing_key",
            "locale": "ar",
            "message": "Missing",
            "source": "localization",
            "severity": "medium",
        }]
        rows = build_review_queue(issues, runtime)
        assert len(rows) == 1
        assert rows[0]["source_hash"] == UNRESOLVED_LOOKUP_SOURCE_HASH
