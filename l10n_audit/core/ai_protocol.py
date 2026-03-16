"""
AI Provider Protocol for dependency injection.

Any callable object that satisfies :class:`AIProvider` can be passed to
:func:`run_audit` as the *ai_provider* parameter.  The production
:class:`~l10n_audit.core.ai_http_provider.HttpAIProvider` uses the real
OpenAI-compatible HTTP API; tests inject
:class:`~l10n_audit.core.mock_ai_provider.MockAIProvider` instead.

Usage::

    from l10n_audit.core.ai_protocol import AIProvider

    class MyCustomProvider:
        def review_batch(self, batch: list[dict], config: dict) -> list[dict]:
            ...
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Protocol for AI review providers.

    Parameters
    ----------
    batch:
        A list of dicts, each with keys:
        ``key``, ``source``, ``current_translation``, ``identified_issue``.
    config:
        A dict with keys ``api_key``, ``api_base``, ``model``.

    Returns
    -------
    list[dict]:
        A list of fix dicts, each with keys ``key``, ``suggestion``,
        ``reason`` (optional).  May return an empty list or ``[]`` on failure.
    """

    def review_batch(self, batch: list[dict], config: dict) -> list[dict]:
        ...
