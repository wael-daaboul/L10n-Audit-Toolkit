
import pytest
from pathlib import Path
from l10n_audit.reports.report_aggregator import (
    build_review_queue, 
    apply_workflow_state_to_rows, 
    compute_text_hash
)

def _runtime():
    return type("Runtime", (), {
        "en_file": "en.json", "ar_file": "ar.json", "locale_format": "json",
        "source_locale": "en", "target_locales": ("ar",),
        "results_dir": ".", "project_root": Path("."), "plan_id": "P1"
    })()

def test_phase12_resolved_row_suppression():
    # PROOF: Applied rows do not reappear if they become no-ops in the next run.
    issues = [{
        "key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
        "current_value": "Hello.", "suggested_fix": "Hello.", "source": "ar_qc"
    }]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Hello."
        })
        review_rows = build_review_queue(issues, _runtime())
        # Row is suppressed because suggestion == current.
        assert len(review_rows) == 0

def test_phase12_stale_row_defense():
    # PROOF: Decisions are invalidated if source text changes (Hash mismatch).
    h1 = compute_text_hash("OldText")
    ws_entry = {
        "approved_new": "NewText",
        "status": "applied",
        "source_hash": h1
    }
    workflow_state = {"P1": ws_entry}
    
    h2 = compute_text_hash("MutatedText")
    current_row = {
        "plan_id": "P1",
        "key": "k1", "locale": "ar", "old_value": "MutatedText",
        "approved_new": "", # Initial state from build_review_queue
        "source_hash": h2, "status": "pending", "notes": "Issue found"
    }
    
    result = apply_workflow_state_to_rows([current_row], workflow_state)
    reprojected = result[0]
    
    assert reprojected["status"] == "stale"
    assert "[DQ:STALE_DECISION]" in reprojected["notes"]
    assert reprojected["needs_review"] == "Yes"
    # Previous approval was NOT applied because it's unsafe
    assert reprojected["approved_new"] != "NewText"

def test_phase12_deterministic_applied_transition():
    # PROOF: Transitions remain deterministic if hashes match.
    h1 = compute_text_hash("ExactText")
    ws_entry = {
        "approved_new": "AppliedText",
        "status": "applied",
        "source_hash": h1
    }
    workflow_state = {"P1": ws_entry}
    current_row = {
        "plan_id": "P1",
        "key": "k1", "locale": "ar", "old_value": "ExactText",
        "approved_new": "",
        "source_hash": h1, "status": "pending"
    }
    result = apply_workflow_state_to_rows([current_row], workflow_state)
    reprojected = result[0]
    assert reprojected["status"] == "applied"
    assert reprojected["approved_new"] == "AppliedText"
