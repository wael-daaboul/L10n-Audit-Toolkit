import json
from unittest.mock import patch, MagicMock
from l10n_audit.core.ai_factory import get_ai_provider, LiteLLMProvider

def test_factory_returns_litellm_by_default():
    provider = get_ai_provider()
    assert isinstance(provider, LiteLLMProvider)

@patch("litellm.completion")
def test_litellm_provider_routing(mock_completion):
    # Mock response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content=json.dumps({"fixes": [{"key": "k1", "suggestion": "s1"}]})))
    ]
    mock_completion.return_value = mock_response

    provider = LiteLLMProvider()
    batch = [{"key": "k1", "source": "src1", "current_translation": "cur1", "identified_issue": "err1"}]
    config = {
        "api_key": "sk-123",
        "model": "gpt-4",
        "api_base": "https://api.openai.com/v1",
        "provider": "litellm"
    }

    with patch("l10n_audit.ai.prompts.get_review_prompt", return_value="prompt text"), \
         patch("l10n_audit.ai.verification.verify_batch_fixes", side_effect=lambda b, f: f):
        fixes = provider.review_batch(batch, config)

    assert len(fixes) == 1
    assert fixes[0]["suggestion"] == "s1"
    
    # Verify litellm was called with correct params
    mock_completion.assert_called_once()
    args, kwargs = mock_completion.call_args
    assert kwargs["model"] == "gpt-4"
    assert kwargs["api_key"] == "sk-123"
    assert kwargs["base_url"] == "https://api.openai.com/v1"
    assert kwargs["temperature"] == 0.0

@patch("litellm.completion")
def test_litellm_provider_cleans_markdown(mock_completion):
    # Mock response with markdown code block
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(content="```json\n{\"fixes\": [{\"key\": \"k1\", \"suggestion\": \"s1\"}]}\n```"))
    ]
    mock_completion.return_value = mock_response

    provider = LiteLLMProvider()
    batch = [{"key": "k1", "source": "src1", "current_translation": "cur1"}]
    config = {"api_key": "sk-1"}

    with patch("l10n_audit.ai.prompts.get_review_prompt", return_value="prompt"), \
         patch("l10n_audit.ai.verification.verify_batch_fixes", side_effect=lambda b, f: f):
        fixes = provider.review_batch(batch, config)

    assert len(fixes) == 1
    assert fixes[0]["suggestion"] == "s1"
