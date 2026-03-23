import pytest
from unittest.mock import MagicMock, patch
from l10n_audit.models import AuditOptions, AIReview
from l10n_audit.exceptions import AIConfigError

def test_chunk_issues():
    issues = list(range(105))
    from l10n_audit.audits.ai_review import chunk_issues
    chunks = list(chunk_issues(issues, batch_size=50))
    assert len(chunks) == 3
    assert len(chunks[0]) == 50
    assert len(chunks[1]) == 50
    assert len(chunks[2]) == 5

def test_run_stage_raises_if_not_enabled():
    runtime = MagicMock()
    options = AuditOptions(ai_review=AIReview(enabled=False))
    from l10n_audit.audits.ai_review import run_stage
    with pytest.raises(AIConfigError) as excinfo:
        run_stage(runtime, options)
    assert "AI review requested but not enabled" in str(excinfo.value)

@patch("time.sleep")
@patch("l10n_audit.audits.ai_review.load_issues")
@patch("l10n_audit.audits.ai_review.load_locale_mapping")
@patch("l10n_audit.core.ai_factory.get_ai_provider")
def test_run_stage_batching_sleep(mock_get_provider, mock_load_locale, mock_load_issues, mock_sleep):
    runtime = MagicMock()
    runtime.en_file = "en.json"
    runtime.ar_file = "ar.json"
    runtime.source_locale = "en"
    runtime.target_locales = ["ar"]
    
    options = AuditOptions(ai_review=AIReview(enabled=True, api_key_env="OPENAI_API_KEY"))
    
    # Mock issues (more than 50 to trigger batching)
    mock_load_issues.return_value = [{"key": f"k{i}", "message": "msg"} for i in range(55)]
    mock_load_locale.return_value = {f"k{i}": "val" for i in range(55)}
    
    mock_provider = MagicMock()
    mock_provider.review_batch.return_value = []
    mock_get_provider.return_value = mock_provider
    
    with patch("l10n_audit.core.validators.validate_ai_config", return_value={}):
        from l10n_audit.audits.ai_review import run_stage
        run_stage(runtime, options)
    
    # 55 items, batch size 20 (default) -> 3 batches. Should sleep twice.
    # Wait, previous test said 55 items, batch size 50 -> 2 batches.
    # Let's check the default batch_size in AIReview. It is 20.
    # So 55 items -> 3 batches.
    assert mock_provider.review_batch.call_count == 3
    assert mock_sleep.call_count == 2
