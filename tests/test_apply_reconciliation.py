"""Tests for reconcile_master_from_xlsx (Phase 1 — Master Reconciliation)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from l10n_audit.fixes.apply_review_fixes import reconcile_master_from_xlsx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_master(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_master(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _write_xlsx(path: Path, data: list[dict]) -> None:
    pd.DataFrame(data).to_excel(path, index=False)


# ---------------------------------------------------------------------------
# Test 1 — Basic update: approved_new synced from XLSX into JSON
# ---------------------------------------------------------------------------

def test_basic_approved_new_update(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "review_queue.xlsx"
    master_path = tmp_path / "audit_master.json"

    _write_xlsx(xlsx_path, [{"plan_id": "123", "approved_new": "New Value"}])
    _write_master(master_path, [
        {"plan_id": "123", "key": "home.title", "locale": "ar", "approved_new": "", "status": "", "notes": ""}
    ])

    reconcile_master_from_xlsx(str(xlsx_path), str(master_path))

    rows = _read_master(master_path)
    assert rows[0]["approved_new"] == "New Value"


# ---------------------------------------------------------------------------
# Test 2 — Missing plan_id in XLSX row: ignored safely, master unchanged
# ---------------------------------------------------------------------------

def test_missing_plan_id_in_xlsx_is_ignored(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "review_queue.xlsx"
    master_path = tmp_path / "audit_master.json"

    # Row has no plan_id column value (NaN after read_excel)
    _write_xlsx(xlsx_path, [{"plan_id": None, "approved_new": "Should Not Apply"}])
    _write_master(master_path, [
        {"plan_id": "abc", "key": "home.title", "locale": "ar", "approved_new": "Original", "status": "", "notes": ""}
    ])

    reconcile_master_from_xlsx(str(xlsx_path), str(master_path))

    rows = _read_master(master_path)
    assert rows[0]["approved_new"] == "Original"


# ---------------------------------------------------------------------------
# Test 3 — plan_id in XLSX not found in JSON: no crash, JSON unchanged
# ---------------------------------------------------------------------------

def test_unknown_plan_id_leaves_master_unchanged(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "review_queue.xlsx"
    master_path = tmp_path / "audit_master.json"

    _write_xlsx(xlsx_path, [{"plan_id": "UNKNOWN-999", "approved_new": "Ghost Value"}])
    _write_master(master_path, [
        {"plan_id": "abc", "key": "home.title", "locale": "ar", "approved_new": "Original", "status": "", "notes": ""}
    ])

    reconcile_master_from_xlsx(str(xlsx_path), str(master_path))

    rows = _read_master(master_path)
    assert rows[0]["approved_new"] == "Original"
    assert rows[0]["plan_id"] == "abc"


# ---------------------------------------------------------------------------
# Test 4 — Status column present: JSON status updated
# ---------------------------------------------------------------------------

def test_status_updated_when_column_present(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "review_queue.xlsx"
    master_path = tmp_path / "audit_master.json"

    _write_xlsx(xlsx_path, [{"plan_id": "456", "approved_new": "Fixed Text", "status": "approved"}])
    _write_master(master_path, [
        {"plan_id": "456", "key": "nav.home", "locale": "ar", "approved_new": "", "status": "", "notes": ""}
    ])

    reconcile_master_from_xlsx(str(xlsx_path), str(master_path))

    rows = _read_master(master_path)
    assert rows[0]["approved_new"] == "Fixed Text"
    assert rows[0]["status"] == "approved"


# ---------------------------------------------------------------------------
# Test 5 — Partial columns (no status column): only approved_new updated
# ---------------------------------------------------------------------------

def test_partial_columns_no_status(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "review_queue.xlsx"
    master_path = tmp_path / "audit_master.json"

    # XLSX has no 'status' column at all
    _write_xlsx(xlsx_path, [{"plan_id": "789", "approved_new": "Partial Update"}])
    _write_master(master_path, [
        {"plan_id": "789", "key": "footer.text", "locale": "ar", "approved_new": "", "status": "pending", "notes": ""}
    ])

    reconcile_master_from_xlsx(str(xlsx_path), str(master_path))

    rows = _read_master(master_path)
    assert rows[0]["approved_new"] == "Partial Update"
    # status must be untouched — XLSX had no status column
    assert rows[0]["status"] == "pending"
