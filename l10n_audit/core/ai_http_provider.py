"""
HTTP AI Provider — production implementation of :class:`AIProvider`.

Wraps the existing :func:`ai.provider.request_ai_review` so it satisfies
the :class:`~l10n_audit.core.ai_protocol.AIProvider` protocol.
"""
from __future__ import annotations

from l10n_audit.ai.provider import request_ai_review


class HttpAIProvider:
    """Production AI provider that calls an OpenAI-compatible HTTP API."""

    def review_batch(self, batch: list[dict], config: dict, glossary: dict | None = None) -> list[dict]:
        """Send *batch* to the AI API and return verified fix dicts.
 
        Returns an empty list if the request fails or yields no usable
        response.
        """
        from l10n_audit.ai.prompts import get_review_prompt
        from l10n_audit.ai.verification import verify_batch_fixes
        from l10n_audit.ai.provider import request_ai_review

        prompt = get_review_prompt(batch, {})
        response = request_ai_review(prompt, config, original_batch=batch, glossary=glossary)
        if response and "fixes" in response:
            return verify_batch_fixes(batch, response["fixes"], glossary=glossary)
        return []

    def request(self, system_prompt: str, batch: list[dict], config: dict | None = None) -> dict:
        """New generic request interface for use with AISiftingReviewer."""
        from l10n_audit.ai.provider import request_ai_review
        # Merge system prompt with batch prompt or handle separately
        # For now, we'll prefix the system prompt to the user prompt logic
        return request_ai_review(system_prompt, config or {})

