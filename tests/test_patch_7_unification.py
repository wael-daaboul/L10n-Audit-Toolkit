import pytest
from pathlib import Path
from l10n_audit.core.locale_utils import (
    resolve_issue_locale,
    resolve_issue_current_value,
    resolve_issue_candidate_value,
    get_value_smart
)
from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
from l10n_audit.reports.report_aggregator import suggested_fix_for_issue

class TestPatch7Unification:
    
    # 1. Test shared locale resolution parity
    def test_locale_resolution_parity(self):
        issues = [
            {"source": "ar_locale_qc", "key": "k1"},
            {"source": "grammar", "key": "k2"},
            {"source": "ai_review", "key": "k3", "locale": "ar"},
            {"source": "ai_review", "key": "k4"}, # Should fallback to 'ar' via source map
            {"key": "ar.prefix.test"},
            {"file_path": "path/to/en.json", "key": "k5"},
        ]
        
        expected = ["ar", "en", "ar", "ar", "ar", "en"]
        
        for issue, exp in zip(issues, expected):
            loc, _src = resolve_issue_locale(issue)
            assert loc == exp
            
    # 2. Test LanguageTool replacement list normalization
    def test_languagetool_replacement_normalization(self):
        issue = {
            "source": "grammar",
            "key": "k1",
            "details": {
                "replacements": ["Correct Text", "Other Option"]
            }
        }
        
        val, src = resolve_issue_candidate_value(issue)
        assert val == "Correct Text"
        assert src == "replacements[0]"
        
        # Test nested dict in replacements
        issue_dict = {
            "details": {
                "replacements": [{"value": "Object Text"}]
            }
        }
        val2, src2 = resolve_issue_candidate_value(issue_dict)
        assert val2 == "Object Text"
        assert src2 == "replacements[0]"

    # 3. Test smart lookup for nested keys
    def test_smart_lookup_nested_keys(self):
        locale_data = {
            "messages.contact_with_us": "اتصل بنا",
            "auth.login": "تسجيل الدخول",
            "simple_key": "قيمة بسيطة"
        }
        
        # Exact match
        assert get_value_smart("simple_key", locale_data) == "قيمة بسيطة"
        # Suffix match
        assert get_value_smart("contact_with_us", locale_data) == "اتصل بنا"
        assert get_value_smart("login", locale_data) == "تسجيل الدخول"
        # No match
        assert get_value_smart("missing", locale_data) is None

    # 4. Test aggregator/fix-plan parity for candidate extraction
    def test_aggregator_fix_plan_candidate_parity(self):
        issue = {
            "key": "k1",
            "source": "grammar",
            "details": {"old": "Old", "new": "New Value"}
        }
        
        # Fix plan side
        plan = build_fix_plan([issue])
        assert len(plan) > 0
        assert plan[0]["candidate_value"] == "New Value"
        
        # Aggregator side
        agg_val = suggested_fix_for_issue(issue, {}, {})
        assert agg_val == "New Value"

    # 5. Test unresolved values stay None (in utils) or "" (in aggregator legacy)
    def test_unresolved_values(self):
        issue = {"key": "k1"} # No current or candidate
        
        loc, _ = resolve_issue_locale(issue)
        curr, _ = resolve_issue_current_value(issue)
        cand, _ = resolve_issue_candidate_value(issue)
        
        assert loc is None
        assert curr is None
        assert cand is None
        
        # build_fix_plan should reject it (it has strict missing_fields check)
        plan = build_fix_plan([issue])
        assert len(plan) == 0

    # 6. Test specific LanguageTool contract in suggested_fix_for_issue
    def test_aggregator_handles_lt_array_correctly(self):
        issue = {
            "key": "k1",
            "source": "grammar",
            "details": {
                "replacements": ["Better Text"]
            }
        }
        # Before Patch 7, this might have returned "['Better Text']" or been missed 
        # depending on which field aggregator looked at first.
        # Now it should return "Better Text".
        val = suggested_fix_for_issue(issue, {}, {})
        assert val == "Better Text"
