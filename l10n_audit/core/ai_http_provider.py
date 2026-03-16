"""
HTTP AI Provider — production implementation of :class:`AIProvider`.

Wraps the existing :func:`ai.provider.request_ai_review` so it satisfies
the :class:`~l10n_audit.core.ai_protocol.AIProvider` protocol.
"""
from __future__ import annotations

from ai.provider import request_ai_review


class HttpAIProvider:
    """Production AI provider that calls an OpenAI-compatible HTTP API."""

    def review_batch(self, batch: list[dict], config: dict) -> list[dict]:
        """Send *batch* to the AI API and return verified fix dicts.

        Returns an empty list if the request fails or yields no usable
        response.
        """
        from ai.prompts import get_review_prompt
        from ai.verification import verify_batch_fixes

        prompt = get_review_prompt(batch, {})
        response = request_ai_review(prompt, config)
        if response and "fixes" in response:
            return verify_batch_fixes(batch, response["fixes"])
        return []
