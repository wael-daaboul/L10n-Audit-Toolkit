"""
HTTP AI Provider — production implementation of :class:`AIProvider`.

Wraps the existing :func:`ai.provider.request_ai_review` so it satisfies
the :class:`~l10n_audit.core.ai_protocol.AIProvider` protocol.
"""
from __future__ import annotations

import logging

from l10n_audit.ai.provider import request_ai_review
from l10n_audit.core.ai_trace import emit_ai_fallback, is_ai_debug_mode

logger = logging.getLogger("l10n_audit.ai_http_provider")


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
                item_key = str(item.get("key", "<unknown>"))
                item_glossary = item.get("glossary", {}) if isinstance(item.get("glossary"), dict) else {}
                prompt = get_review_prompt([item], item_glossary, locale=str(item.get("locale", "ar")))
                response = request_ai_review(prompt, config, original_batch=[item], glossary=glossary)
                translated_text = _extract_translated_text(response)
                if translated_text is None:
                    # Phase 9: fallback — provider returned no usable suggestion.
                    _reason = "parse_error" if response is None else "output_contract_violation"
                    emit_ai_fallback(
                        key=item_key,
                        reason=_reason,
                        details={"response_type": type(response).__name__},
                    )
                    if is_ai_debug_mode():
                        logger.debug(
                            "AI PROVIDER: No usable response for key='%s' reason='%s' response=%s",
                            item_key, _reason, response,
                        )
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
        # Phase 9: fallback — legacy batch produced no usable response.
        _batch_keys = [str(item.get("key", "<unknown>")) for item in batch]
        emit_ai_fallback(
            key=", ".join(_batch_keys[:3]) + ("..." if len(_batch_keys) > 3 else ""),
            reason="no_suggestion",
            details={"batch_size": len(batch), "has_response": response is not None},
        )
        return []

    def request(self, system_prompt: str, batch: list[dict], config: dict | None = None) -> dict:
        """New generic request interface for use with AISiftingReviewer."""
        from l10n_audit.ai.provider import request_ai_review
        # Merge system prompt with batch prompt or handle separately
        # For now, we'll prefix the system prompt to the user prompt logic
        return request_ai_review(system_prompt, config or {})
