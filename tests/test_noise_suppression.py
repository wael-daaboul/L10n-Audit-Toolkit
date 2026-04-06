
import pytest
from l10n_audit.reports.report_aggregator import build_review_queue
from unittest.mock import MagicMock

def _runtime():
    return type("Runtime", (), {
        "en_file": "en.json", "ar_file": "ar.json", "locale_format": "json",
        "source_locale": "en", "target_locales": ("ar",)
    })()

def test_noise_suppression_logic():
    # Issue 1: Real suggested fix (Actionable) -> KEEP
    issue1 = {
        "key": "k1", "locale": "ar", "issue_type": "translation_error", "severity": "medium",
        "current_value": "Old", "suggested_fix": "New", "source": "ar_qc"
    }
    # Issue 2: Keep current value (Noise) -> SUPPRESS
    issue2 = {
        "key": "k2", "locale": "ar", "issue_type": "translation_error", "severity": "medium",
        "current_value": "Same", "suggested_fix": "Same", "source": "ar_qc"
    }
    # Issue 3: No candidate found (Noise) -> SUPPRESS
    issue3 = {
        "key": "k3", "locale": "ar", "issue_type": "translation_error", "severity": "medium",
        "current_value": "Test", "suggested_fix": "", "source": "ar_qc"
    }
    # Issue 4: Tag Conflict (Meaningful mismatch) -> KEEP
    issue4 = {
        "key": "k4", "locale": "ar", "issue_type": "tag_mismatch", "severity": "medium",
        "current_value": "<b>Val</b>", "suggested_fix": "Val", # Conflict
        "source": "ar_qc"
    }
    # Issue 5: Brand Safety Block (Meaningful block) -> KEEP
    issue5 = {
        "key": "k5", "locale": "ar", "issue_type": "meaning_loss", "severity": "medium",
        "current_value": "Bkash payment", "suggested_fix": "Brash payment", # Safety block
        "source": "ar_qc"
    }

    issues = [issue1, issue2, issue3, issue4, issue5]
    
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("l10n_audit.reports.report_aggregator.load_locale_mapping", lambda *a, **k: {
            "k1": "Old", "k2": "Same", "k3": "Test", "k4": "<b>Val</b>", "k5": "Bkash payment"
        })
        
        rows = build_review_queue(issues, _runtime())
        
        # Expected results:
        # k1: Keep (New fix)
        # k2: Suppress (Same)
        # k3: Suppress (No candidate)
        # k4: Keep (CONFLICT:STRUCTURAL_RISK)
        # k5: Keep (CONFLICT:SAFETY_VETO / DQ:BLOCKED)
        
        keys = set(row["key"] for row in rows)
        assert "k1" in keys
        assert "k4" in keys
        assert "k5" in keys
        assert "k2" not in keys
        assert "k3" not in keys
        assert len(rows) == 3

