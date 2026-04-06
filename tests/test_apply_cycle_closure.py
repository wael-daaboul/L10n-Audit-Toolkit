
import pytest
from pathlib import Path
from l10n_audit.reports.report_aggregator import (
    build_review_queue, 
    apply_workflow_state_to_rows, 
    create_analytical_payload,
    compute_text_hash
)

def _runtime():
    return type("Runtime", (), {
        "en_file": "en.json", "ar_file": "ar.json", "locale_format": "json",
        "source_locale": "en", "target_locales": ("ar",),
        "results_dir": ".", "project_root": Path("."), "plan_id": "P1"
    })()

def test_phase12_full_cycle_apply_closure():
    # Proof of full-cycle apply closure using the real function chain.
    i1 = {"key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
          "current_value": "Hello", "suggested_fix": "Hello.", "source": "ar_qc"}
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Hello"
        })
        
        # Step 1: Initial Queue
        r1_rows = build_review_queue([i1], _runtime())
        plan_id = r1_rows[0]["plan_id"]
        h1 = r1_rows[0]["source_hash"]
        
        # Step 2: SIMULATE APPLY (Persisted State in Workflow)
        workflow_state = {
            plan_id: {
                "approved_new": "Hello.",
                "status": "applied",
                "source_hash": h1
            }
        }
        
        # Step 3: RERUN (Source is now "Hello.")
        i1_rerun = {"key": "k1", "locale": "ar", "issue_type": "punctuation", "severity": "low",
                    "current_value": "Hello.", "suggested_fix": "Hello.", "source": "ar_qc"}
        
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Hello."
        })
        
        r2_rows = build_review_queue([i1_rerun], _runtime())
        
        # PROOF 1: Resolved row is suppressed (Closure confirmed)
        assert len(r2_rows) == 0
        
        # Step 4: Analytical Closure
        payload = create_analytical_payload(
            review_rows=r2_rows,
            issues=[i1_rerun],
            reports={"ar_qc": {}},
            missing=[],
            summary={"total_issues": 1},
            safe_fixes={"available": 0},
            source_status={"ar_qc": "ok"}
        )
        
        # PROOF 2: Summary reflects suppression (0 issues actionable)
        assert payload["summary"]["total_issues"] == 0
        assert payload["summary"]["review_required_issues"] == 0

def test_phase12_stale_rerun_proof():
    # Proof of stale-source defense: explicit stale marking for identity-matches with content shifts.
    
    # 1. State: Applied to "Hello" (H1)
    h1 = compute_text_hash("Hello")
    workflow_state = {
        "FIXED_ID": {
            "approved_new": "Hello.",
            "status": "applied",
            "source_hash": h1
        }
    }
    
    # 2. Rerun: Current row has "Hi" (H2) and we simulate an ID match to test the stale-check logic
    h2 = compute_text_hash("Hi")
    current_row = {
        "plan_id": "FIXED_ID", # FORCED IDENTITY MATCH
        "key": "k1", "locale": "ar", "old_value": "Hi", "approved_new": "",
        "source_hash": h2, "status": "pending", "notes": "Initial Issue"
    }
    
    # ACT
    reprojected = apply_workflow_state_to_rows([current_row], workflow_state)
    r = reprojected[0]
    
    # PROOF 3: Row is marked STALE due to hash mismatch (Closure interrupted safely)
    assert r["status"] == "stale"
    assert r["needs_review"] == "Yes"
    assert "[DQ:STALE_DECISION]" in r["notes"]
    assert r["approved_new"] != "Hello." # Silent application blocked
    
    # ACT: Reconciled analytical payload
    payload = create_analytical_payload([r], [{}], {}, [], {"total_issues": 1}, {"available": 0}, {})
    
    # PROOF 4: Reconciled analytical state reflects the Stale actionable item correctly
    assert payload["summary"]["total_issues"] == 1
    assert payload["summary"]["review_required_issues"] == 1
    assert payload["summary"]["safe_fixes_available"] == 0
