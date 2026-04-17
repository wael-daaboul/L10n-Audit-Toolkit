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

        def _is_structured_payload(item: dict) -> bool:
            return {"key", "source_text", "current_text", "locale", "placeholders", "glossary"}.issubset(item.keys())

        def _extract_translated_text(response: dict | None) -> str | None:
            if not isinstance(response, dict):
                return None
            translated_text = response.get("translated_text")
            if isinstance(translated_text, str) and translated_text.strip():
                return translated_text.strip()
            return None

        if batch and all(_is_structured_payload(item) for item in batch):
            fixes: list[dict] = []
            for item in batch:
                item_glossary = item.get("glossary", {}) if isinstance(item.get("glossary"), dict) else {}
                prompt = get_review_prompt([item], item_glossary, locale=str(item.get("locale", "ar")))
                response = request_ai_review(prompt, config, original_batch=[item], glossary=glossary)
                translated_text = _extract_translated_text(response)
                if translated_text is None:
                    continue
                fixes.append(
                    {
                        "key": item.get("key"),
                        "suggestion": translated_text,
                        "reason": "Structured AI translation",
                    }
                )
            if not fixes:
                return []
            return verify_batch_fixes(batch, fixes, glossary=glossary)

        # Legacy batch compatibility path.
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
