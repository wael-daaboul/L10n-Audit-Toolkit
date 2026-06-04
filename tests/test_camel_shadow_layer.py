"""test_camel_shadow_layer.py

Invariant tests for the CAMeL Shadow Review Layer.

The binding contract:
    same rows in, same rows out          — row count never changes
    only camel_* columns added            — no existing key mutated
    camel_* visible in review_queue.xlsx  — build_human_review_queue forwards them
    apply_review_fixes never reads camel_* — apply contract untouched
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from l10n_audit.core.camel_decorator import CAMEL_FIELDS, decorate_with_camel
from l10n_audit.reports.report_aggregator import (
    build_review_queue,
    build_human_review_queue,
    REVIEW_QUEUE_WORKBOOK_COLUMNS,
    REVIEW_PROJECTION_COLUMNS,
)
from l10n_audit.fixes.apply_review_fixes import REQUIRED_REVIEW_COLUMNS, APPLY_REQUIRED_FIELDS

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

CORE_REVIEW_FIELDS = [
    "key",
    "locale",
    "old_value",
    "issue_type",
    "suggested_fix",
    "approved_new",
    "needs_review",
    "status",
    "notes",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
]

CORE_WORKBOOK_FIELDS = [
    "key",
    "locale",
    "issue_type",
    "current_value",
    "candidate_value",
    "status",
    "review_note",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
]


def _runtime(camel_enabled: bool = False):
    return type("Runtime", (), {
        "en_file": "en.json",
        "ar_file": "ar.json",
        "locale_format": "json",
        "source_locale": "en",
        "target_locales": ("ar",),
        "results_dir": ".",
        "camel_enabled": camel_enabled,
        "config": {"camel_enabled": camel_enabled},
    })()


def _make_issue(key: str = "k1", locale: str = "ar") -> dict:
    return {
        "key": key,
        "locale": locale,
        "issue_type": "punctuation",
        "severity": "low",
        "current_value": "مرحبا",
        "suggested_fix": "مرحبا.",
        "source": "ar_locale_qc",
        "needs_review": False,
    }


def _build_rows(issues, camel_enabled: bool = False):
    rt = _runtime(camel_enabled)
    with patch(
        "l10n_audit.reports.report_aggregator.load_locale_mapping",
        lambda *a, **k: {i["key"]: i.get("current_value", "") for i in issues},
    ):
        return build_review_queue(issues, rt)


# ------------------------------------------------------------------
# T-1  Row count unchanged when CAMeL is disabled
# ------------------------------------------------------------------

def test_row_count_unchanged_camel_disabled():
    issues = [_make_issue("k1"), _make_issue("k2"), _make_issue("k3")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = _runtime(camel_enabled=False)
    decorated = decorate_with_camel(rows, rt)
    assert len(decorated) == len(rows)


# ------------------------------------------------------------------
# T-2  Row count unchanged when CAMeL is enabled
# ------------------------------------------------------------------

def test_row_count_unchanged_camel_enabled():
    issues = [_make_issue("k1"), _make_issue("k2")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = _runtime(camel_enabled=True)
    decorated = decorate_with_camel(rows, rt)
    assert len(decorated) == len(rows)


# ------------------------------------------------------------------
# T-3  All existing columns unchanged after decoration; camel_* added
# ------------------------------------------------------------------

def test_existing_columns_unchanged_camel_fields_added():
    issues = [_make_issue("k1")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = _runtime(camel_enabled=True)
    decorated = decorate_with_camel(rows, rt)

    for before, after in zip(rows, decorated):
        # Core fields must be bit-identical
        for field in CORE_REVIEW_FIELDS:
            if field in before:
                assert before[field] == after[field], f"CAMeL mutated field {field!r}"
        # camel_* keys must be present in the output
        for col in CAMEL_FIELDS:
            assert col in after, f"Expected camel field {col!r} in decorated row"
        # camel_* keys must NOT have been present before decoration
        for col in CAMEL_FIELDS:
            assert col not in before, f"camel field {col!r} should not exist before decoration"


# ------------------------------------------------------------------
# T-4  Suppressed rows stay suppressed (never reach decorate_with_camel)
# ------------------------------------------------------------------

def test_suppressed_rows_absent_from_decorated_output():
    # An info-severity issue (non-AI) is suppressed by build_review_queue.
    suppressed_issue = {
        "key": "suppressed_key",
        "locale": "ar",
        "issue_type": "duplicate_value",
        "severity": "info",
        "current_value": "نعم",
        "source": "ar_locale_qc",
    }
    admitted_issue = _make_issue("admitted_key")

    rows = _build_rows([suppressed_issue, admitted_issue], camel_enabled=False)
    rt = _runtime(camel_enabled=True)
    decorated = decorate_with_camel(rows, rt)

    keys = [r["key"] for r in decorated]
    assert "suppressed_key" not in keys, "suppressed row must not appear after decoration"
    assert "admitted_key" in keys, "admitted row must appear after decoration"


# ------------------------------------------------------------------
# T-5  CAMeL failure does not drop rows; falls back to empty strings
# ------------------------------------------------------------------

def test_camel_failure_does_not_drop_rows():
    issues = [_make_issue("k1"), _make_issue("k2")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = _runtime(camel_enabled=True)

    with patch(
        "l10n_audit.core.camel_decorator._analyse_row",
        side_effect=RuntimeError("CAMeL backend down"),
    ):
        decorated = decorate_with_camel(rows, rt)

    assert len(decorated) == len(rows), "Row count must be unchanged even on backend failure"
    for before, after in zip(rows, decorated):
        for field in CORE_REVIEW_FIELDS:
            if field in before:
                assert before[field] == after[field], f"Field {field!r} mutated on failure"
        for col in CAMEL_FIELDS:
            assert col in after, f"camel field {col!r} must be present even on failure"
            assert after[col] == "", f"camel field {col!r} must be empty string on failure"


# ------------------------------------------------------------------
# T-6  build_human_review_queue: core fields unchanged, camel_* visible
# ------------------------------------------------------------------

def test_build_human_review_queue_camel_columns_visible():
    issues = [_make_issue("k1"), _make_issue("k2")]
    rows_raw = _build_rows(issues, camel_enabled=False)
    rows_decorated = decorate_with_camel(rows_raw, _runtime(camel_enabled=True))

    human_before = build_human_review_queue(rows_raw)
    human_after = build_human_review_queue(rows_decorated)

    assert len(human_before) == len(human_after), "Row count must be identical"

    for before, after in zip(human_before, human_after):
        # Core workbook fields must be bit-identical
        for field in CORE_WORKBOOK_FIELDS:
            if field in before:
                assert before[field] == after[field], (
                    f"Core workbook field {field!r} mutated after CAMeL decoration"
                )
        # camel_* columns must now be present in every workbook row
        for col in CAMEL_FIELDS:
            assert col in after, (
                f"camel field {col!r} must be present in human review queue row"
            )


# ------------------------------------------------------------------
# T-7  camel_* values actually appear in REVIEW_QUEUE_WORKBOOK_COLUMNS
# ------------------------------------------------------------------

def test_camel_fields_in_workbook_column_list():
    for col in CAMEL_FIELDS:
        assert col in REVIEW_QUEUE_WORKBOOK_COLUMNS, (
            f"{col!r} must be in REVIEW_QUEUE_WORKBOOK_COLUMNS"
        )
    # Verify core workbook columns are still in their original relative order
    core_order = [c for c in REVIEW_QUEUE_WORKBOOK_COLUMNS if not c.startswith("camel_")]
    assert core_order == CORE_WORKBOOK_FIELDS, "Core workbook column order must not change"


# ------------------------------------------------------------------
# T-8  camel_* values appear in REVIEW_PROJECTION_COLUMNS (JSON output)
# ------------------------------------------------------------------

def test_camel_fields_in_projection_column_list():
    for col in CAMEL_FIELDS:
        assert col in REVIEW_PROJECTION_COLUMNS, (
            f"{col!r} must be in REVIEW_PROJECTION_COLUMNS"
        )
    # camel_* must be the tail — all come after the 22 core columns
    core_end_idx = REVIEW_PROJECTION_COLUMNS.index("semantic_gate_status")
    camel_start_idx = REVIEW_PROJECTION_COLUMNS.index("camel_available")
    assert camel_start_idx > core_end_idx, (
        "CAMeL columns must be appended after all core projection columns"
    )


# ------------------------------------------------------------------
# T-9  apply_review_fixes never reads any camel_* field
# ------------------------------------------------------------------

def test_apply_contract_columns_do_not_contain_camel():
    all_apply_columns = set(REQUIRED_REVIEW_COLUMNS) | set(APPLY_REQUIRED_FIELDS)
    for col in CAMEL_FIELDS:
        assert col not in all_apply_columns, (
            f"apply_review_fixes must not read camel field {col!r}; "
            "CAMeL is a shadow layer only"
        )


# ------------------------------------------------------------------
# T-10  decorate_with_camel is a pure pass-through when camel_enabled=False
# ------------------------------------------------------------------

def test_camel_disabled_passthrough():
    issues = [_make_issue("k1")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = _runtime(camel_enabled=False)
    decorated = decorate_with_camel(rows, rt)
    assert len(decorated) == len(rows)
    for before, after in zip(rows, decorated):
        for field in CORE_REVIEW_FIELDS:
            if field in before:
                assert before[field] == after[field]
        # camel_* should still be present but empty
        for col in CAMEL_FIELDS:
            assert col in after
            assert after[col] == ""


# ------------------------------------------------------------------
# T-11  Support nested arabic_nlp config block
# ------------------------------------------------------------------

def test_camel_enabled_by_nested_arabic_nlp_config():
    issues = [_make_issue("k1")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = type("Runtime", (), {
        "camel_enabled": None,
        "config": {
            "arabic_nlp": {
                "enabled": True,
                "provider": "camel_tools",
                "shadow_mode": True,
                "enable_dialect": False
            }
        }
    })()
    decorated = decorate_with_camel(rows, rt)
    assert len(decorated) == len(rows)
    for row in decorated:
        assert row["camel_available"] in ("yes", "no")
        assert row["camel_reason"] != ""


def test_camel_enable_dialect_by_nested_config():
    issues = [_make_issue("k1")]
    rows = _build_rows(issues, camel_enabled=False)
    rt = type("Runtime", (), {
        "camel_enabled": None,
        "config": {
            "arabic_nlp": {
                "enabled": True,
                "enable_dialect": True
            }
        }
    })()
    with patch("l10n_audit.core.camel_decorator.analyze_arabic_text") as mock_analyze:
        mock_analyze.return_value = {}
        decorate_with_camel(rows, rt)
        mock_analyze.assert_called_once_with("مرحبا", enable_dialect=True)

