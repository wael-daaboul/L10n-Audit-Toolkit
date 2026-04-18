
import pytest
import os
import json
import re
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from l10n_audit.reports.report_aggregator import build_review_queue, REVIEW_QUEUE_COLUMNS, _normalize_review_row
from l10n_audit.core.audit_runtime import write_simple_xlsx
from l10n_audit.fixes.fix_merger import REVIEW_FINAL_COLUMNS

def _runtime():
    return type("Runtime", (), {
        "en_file": "en.json", "ar_file": "ar.json", "locale_format": "json",
        "source_locale": "en", "target_locales": ("ar",),
        "results_dir": "."
    })()

def test_exact_20_column_freeze():
    # Phase 8: schema now has 22 columns (added ai_outcome_decision, semantic_gate_status)
    assert len(REVIEW_QUEUE_COLUMNS) == 22
    
    # 2. Verify exact ordered parity of a representative materialized row
    issue = {
        "key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
        "current_value": "Hello", "suggested_fix": "Hello.", "source": "ar_qc",
        "needs_review": False
    }
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {"k1": "Hello"})
        rows = build_review_queue([issue], _runtime())
        assert len(rows) == 1
        row = rows[0]
        
        # EXACT PUBLIC column count and order check (Exclude internal metadata)
        actual_keys = [k for k in row.keys() if not k.startswith("_")]
        assert len(actual_keys) == 22
        assert actual_keys == REVIEW_QUEUE_COLUMNS

def test_json_xlsx_parity_readback(tmp_path):
    rows = [
        {col: f"val_{i}" for i, col in enumerate(REVIEW_QUEUE_COLUMNS)}
    ]
    json_path = tmp_path / "rq.json"
    xlsx_path = tmp_path / "rq.xlsx"
    
    # Export
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    write_simple_xlsx(rows, REVIEW_QUEUE_COLUMNS, xlsx_path, sheet_name="Review Queue")
    
    # JSON Readback & Parity
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)
    assert len(json_data) == 1
    assert list(json_data[0].keys()) == REVIEW_QUEUE_COLUMNS
    
    # XLSX Readback & Parity (using ZipFile/XML)
    with ZipFile(xlsx_path, 'r') as zip_ref:
        with zip_ref.open('xl/sharedStrings.xml') as f:
            tree = ET.parse(f)
            shared_strings = [t.text for t in tree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')]
        
        with zip_ref.open('xl/worksheets/sheet1.xml') as f:
            tree = ET.parse(f)
            first_row = tree.find('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row[@r="1"]')
            header_v_elements = first_row.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
            xlsx_headers = [shared_strings[int(v.text)] for v in header_v_elements]
            all_rows = tree.findall('.//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row')
            xlsx_row_count = len(all_rows) - 1
    
    assert len(xlsx_headers) == 22
    assert xlsx_headers == REVIEW_QUEUE_COLUMNS
    assert xlsx_row_count == 1
    assert xlsx_headers == list(json_data[0].keys())

def test_strict_token_discipline():
    # Final Frozen Notes Vocabulary (Phase 10 Hardened)
    ALLOWED_TOKENS = {
        "[DQ:SAFE_AUTO_PROJECTED]",
        "[DQ:SUGGESTION_ONLY]",
        "[DQ:BLOCKED]",
        "[DQ:REVIEW_REQUIRED]",
        "[CONFLICT:STRUCTURAL_RISK]",
        "[CONFLICT:SAFETY_VETO]",
        "[KEEP:CURRENT_VALUE]",
        "[NO_CANDIDATE]"
    }
    
    def check_row_tokens(row, expected_token=None):
        notes = row.get("notes", "")
        # Extract segments that look like tokens [ABC:XYZ]
        found_tokens = re.findall(r"\[[A-Z_:]+]", notes)
        for t in found_tokens:
            assert t in ALLOWED_TOKENS, f"Unexpected token variant found: {t}"
        if expected_token:
            assert expected_token in found_tokens, f"Expected token {expected_token} not found in {notes}"

    # Verify semantic row categories
    # 1. safe_auto_projected (Mechanical)
    issue_safe = {
        "key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
        "current_value": "Hello", "suggested_fix": "Hello.", "source": "ar_qc", "needs_review": False
    }
    # 2. suggestion_only (Semantic rewrite)
    issue_suggest = {
        "key": "key2", "locale": "ar", "issue_type": "meaning_loss", "severity": "medium",
        "current_value": "Submit", "suggested_fix": "Finish registration", "source": "ar_qc"
    }
    # 3. blocked_brand (Safety block)
    issue_blocked = {
        "key": "key3", "locale": "ar", "issue_type": "meaning_loss", "severity": "medium",
        "current_value": "Bkash Pay", "suggested_fix": "bkash pay", "source": "ar_qc"
    }
    # 4. structural_conflict (Tag mismatch)
    issue_conflict = {
        "key": "key4", "locale": "ar", "issue_type": "tag_mismatch", "severity": "medium",
        "current_value": "<b>OK</b>", "suggested_fix": "OK", "source": "ar_qc"
    }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Hello", "key2": "Submit", "key3": "Bkash Pay", "key4": "<b>OK</b>"
        })
        rows = build_review_queue([issue_safe, issue_suggest, issue_blocked, issue_conflict], _runtime())
        row_map = {row["key"]: row for row in rows}
        
        # PROOF OF SEMANTIC DISTINCTION
        # Safe
        check_row_tokens(row_map["k1"], "[DQ:SAFE_AUTO_PROJECTED]")
        
        # Suggestion Only (Must NOT be BLOCKED)
        check_row_tokens(row_map["key2"], "[DQ:SUGGESTION_ONLY]")
        assert "[DQ:BLOCKED]" not in row_map["key2"]["notes"]
        
        # Safety Block (Identity mutation)
        check_row_tokens(row_map["key3"], "[DQ:BLOCKED]")
        check_row_tokens(row_map["key3"], "[CONFLICT:SAFETY_VETO]")
        
        # Structural Conflict
        check_row_tokens(row_map["key4"], "[DQ:BLOCKED]")
        check_row_tokens(row_map["key4"], "[CONFLICT:STRUCTURAL_RISK]")

def test_workflow_semantics_hardened():
    # 1. Safe move (Mechanical)
    r1 = _normalize_review_row({
        "old_value": "Hello", "suggested_fix": "Hello.", "approved_new": "Hello.", "needs_review": "No"
    })
    assert r1["needs_review"] == "No"
    
    # 2. Suggestion only (Emptied by DQ)
    r2 = _normalize_review_row({
        "old_value": "Hello", "suggested_fix": "Finish registration", "approved_new": "", "needs_review": "No"
    })
    assert r2["needs_review"] == "Yes" # Forced by Phase 10 logic
    
    # 3. No-Op (Whitespace) -> Suppressed in build_review_queue loop, but _normalize handles edge cases
    r3 = _normalize_review_row({
        "old_value": "Hello", "suggested_fix": "Hello", "approved_new": "", "needs_review": "No"
    })
    assert r3["suggested_fix"] == "" # Cleared effective-only
    assert r3["needs_review"] == "Yes"


def test_review_final_column_freeze():
    assert REVIEW_FINAL_COLUMNS == [
        "key",
        "locale",
        "issue_type",
        "current_value",
        "candidate_value",
        "approved_new",
        "status",
        "review_note",
        "source_old_value",
        "source_hash",
        "suggested_hash",
        "plan_id",
        "generated_at",
        "frozen_artifact_type",   # H1 — artifact type boundary marker
    ]
