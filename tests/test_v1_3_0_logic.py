import sys
from unittest.mock import MagicMock, patch

# Mock litellm to prevent import error during test execution
sys.modules["litellm"] = MagicMock()

import pytest
import json
from pathlib import Path
from l10n_audit.ai.provider import request_ai_review
from l10n_audit.ai.verification import GlossaryViolationError
from l10n_audit.core.results_manager import get_staged_dir, manage_previous_results, migrate_verified_to_staged
from l10n_audit.fixes.apply_safe_fixes import build_fix_plan

# Test 1: Mock AI response violating glossary and check for rejection/retry
@patch("l10n_audit.ai.provider.request_ai_review_litellm")
def test_ai_glossary_violation_retry(mock_litellm):
    # Mock AI returning a forbidden term
    mock_litellm.return_value = {
        "fixes": [{"key": "test_key", "suggestion": "forbidden_word", "reason": "AI made a mistake"}]
    }
    
    glossary = {
        "rules": {
            "forbidden_terms": [{"forbidden_ar": "forbidden_word", "use_instead": "approved_word"}]
        }
    }
    
    config = {"api_key": "fake", "model": "gpt-4"}
    batch = [{"key": "test_key", "source": "English", "current_translation": "Arabic"}]
    
    with pytest.raises(GlossaryViolationError) as excinfo:
        request_ai_review("prompt", config, original_batch=batch, glossary=glossary, max_retries=2)
    
    assert "Glossary enforcement failed" in str(excinfo.value)
    # Ensure it tried exactly 2 times (based on max_retries)
    assert mock_litellm.call_count == 2

# Test 2: Verified translations migrate to staged/ and are preserved
def test_verified_migration_and_preservation(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    results_dir = project_root / "Results"
    results_dir.mkdir()
    
    # Mock results with a verified issue
    class MockIssue:
        def __init__(self, key, locale, target, suggestion, verified):
            self.key = key
            self.locale = locale
            self.target = target
            self.suggestion = suggestion
            self.verified = verified
            self.source = "Source text"
            self.file = "path/to/file.json"

    results = MagicMock()
    results.issues = [MockIssue("k1", "ar", "old", "new", True)]
    
    migrate_verified_to_staged(project_root, results)
    
    staged_file = project_root / ".l10n-audit" / "staged" / "approved_translations.json"
    assert staged_file.exists()
    
    # Check content
    data = json.loads(staged_file.read_text())
    assert "ar:k1" in data
    assert data["ar:k1"]["suggestion"] == "new"
    
    # Test preservation during cleanup
    options = MagicMock()
    options.stage = "full"
    options.output.retention_mode = "overwrite"
    options.output.archive_name_prefix = "audit"
    options.output.archive_name_prefix = "audit"
    
    # Create some dummy file in Results
    dummy_file = results_dir / "dummy.txt"
    dummy_file.write_text("should be deleted")
    
    # manage_previous_results should delete dummy_file but staged_file is outside
    manage_previous_results(results_dir, options)
    assert not dummy_file.exists()
    assert staged_file.exists()

# Test 3: Fix engine ignores unverified AI suggestions
def test_fix_plan_ignores_unverified_ai():
    issues = [
        {
            "key": "k1",
            "source": "ai_review",
            "code": "AI_SUGGESTION",
            "verified": False,
            "suggestion": "bad suggestion",
            "details": {"old": "old", "new": "bad suggestion"}
        },
        {
            "key": "k2",
            "source": "ai_review",
            "code": "AI_SUGGESTION",
            "verified": True,
            "suggestion": "good suggestion",
            "details": {"old": "old", "new": "good suggestion"}
        }
    ]
    
    plan = build_fix_plan(issues)
    
    # Should only contain k2
    keys_in_plan = [item["key"] for item in plan]
    assert "k1" not in keys_in_plan
    assert "k2" in keys_in_plan
