import json
from unittest.mock import patch, MagicMock
from l10n_audit.core.ai_factory import get_ai_provider, LiteLLMProvider

def test_factory_returns_litellm_by_default():
    provider = get_ai_provider()
    assert isinstance(provider, LiteLLMProvider)

@patch("l10n_audit.ai.provider.request_ai_review_litellm")
@patch("l10n_audit.ai.verification.verify_batch_fixes")
@patch("l10n_audit.ai.prompts.get_review_prompt")
def test_litellm_provider_routing(mock_prompt, mock_verify, mock_request):
    mock_prompt.return_value = "prompt text"
    mock_request.return_value = {"fixes": [{"key": "k1", "suggestion": "s1"}]}
    mock_verify.side_effect = lambda b, f: f

    provider = LiteLLMProvider()
    batch = [{"key": "k1", "source": "src1", "current_translation": "cur1", "identified_issue": "err1"}]
    config = {
        "api_key": "sk-123",
        "model": "gpt-4",
    }

    fixes = provider.review_batch(batch, config)

    assert len(fixes) == 1
    assert fixes[0]["suggestion"] == "s1"
    
    # Verify delegation was called properly
    mock_prompt.assert_called_once_with(batch, {})
    mock_request.assert_called_once_with("prompt text", config)
    mock_verify.assert_called_once_with(batch, [{"key": "k1", "suggestion": "s1"}])

@patch("l10n_audit.ai.provider.request_ai_review_litellm")
@patch("l10n_audit.ai.prompts.get_review_prompt")
def test_litellm_provider_handles_empty_or_invalid_response(mock_prompt, mock_request):
    mock_prompt.return_value = "prompt"
    # Provide an invalid response (missing 'fixes' key)
    mock_request.return_value = {"error": "something failed"}

    provider = LiteLLMProvider()
    batch = [{"key": "k1", "source": "src1", "current_translation": "cur1"}]
    config = {"api_key": "sk-1"}

    fixes = provider.review_batch(batch, config)

    # Must return empty list instead of crashing
    assert fixes == []
    mock_request.assert_called_once_with("prompt", config)
