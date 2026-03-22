from __future__ import annotations
import litellm
import json
import logging
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class AIProvider(Protocol):
    def review_batch(self, batch: list[dict], config: dict[str, Any]) -> list[dict]:
        ...

class LiteLLMProvider:
    """Provider-Agnostic AI review provider using LiteLLM."""

    def review_batch(self, batch: list[dict], config: dict[str, Any]) -> list[dict]:
        from ai.prompts import get_review_prompt
        from ai.verification import verify_batch_fixes
        from ai.provider import request_ai_review_litellm

        prompt = get_review_prompt(batch, {})
        response = request_ai_review_litellm(prompt, config)
        
        if response and "fixes" in response:
            return verify_batch_fixes(batch, response["fixes"])
        return []

def get_ai_provider(provider_type: str = "litellm") -> AIProvider:
    """Factory to get the requested AI provider."""
    if provider_type == "litellm":
        return LiteLLMProvider()
    
    # Fallback to legacy
    from l10n_audit.core.ai_http_provider import HttpAIProvider
    return HttpAIProvider()
