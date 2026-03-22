import os
import pytest
from unittest.mock import patch, MagicMock
from l10n_audit.core.validators import validate_ai_config
from l10n_audit.exceptions import AIConfigError

def test_validate_ai_config_direct_key():
    config = validate_ai_config(
        ai_enabled=True,
        ai_api_key="direct-key",
        ai_model="gpt-4",
        ai_provider="openai"
    )
    assert config["api_key"] == "direct-key"
    assert config["model"] == "gpt-4"
    assert config["provider"] == "openai"

def test_validate_ai_config_env_var():
    with patch.dict(os.environ, {"CUSTOM_KEY": "env-key"}):
        config = validate_ai_config(
            ai_enabled=True,
            ai_api_key_env="CUSTOM_KEY",
            ai_model="deepseek-chat",
            ai_provider="litellm"
        )
        assert config["api_key"] == "env-key"
        assert config["model"] == "deepseek-chat"
        assert config["provider"] == "litellm"

def test_validate_ai_config_default_env_var():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "default-key"}):
        config = validate_ai_config(
            ai_enabled=True
        )
        assert config["api_key"] == "default-key"
        assert config["model"] == "gpt-4o-mini"
        assert config["provider"] == "litellm"

def test_validate_ai_config_missing_key_raises():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(AIConfigError) as excinfo:
            validate_ai_config(ai_enabled=True)
        assert "no API key resolved" in str(excinfo.value)

@patch("dotenv.load_dotenv")
def test_validate_ai_config_calls_load_dotenv(mock_load_dotenv):
    with patch.dict(os.environ, {"OPENAI_API_KEY": "some-key"}):
        validate_ai_config(ai_enabled=True)
        mock_load_dotenv.assert_called_once()
