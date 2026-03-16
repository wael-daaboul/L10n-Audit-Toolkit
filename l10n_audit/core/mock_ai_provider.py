"""
Mock AI Provider for use in tests.

Inject a :class:`MockAIProvider` into :func:`run_audit` to avoid any network
calls during CI / unit tests::

    from l10n_audit.core.mock_ai_provider import MockAIProvider
    from l10n_audit import run_audit

    mock = MockAIProvider(
        fixes=[{"key": "home.title", "suggestion": "الصفحة الرئيسية", "reason": "mock"}]
    )
    result = run_audit(project_path, stage="ai-review", ai_enabled=True,
                       ai_api_key="fake", ai_provider=mock)
"""
from __future__ import annotations

from typing import Callable


class MockAIProvider:
    """Deterministic AI provider for testing.

    Parameters
    ----------
    fixes:
        Pre-baked list of fix dicts to return for every :meth:`review_batch`
        call.  Defaults to an empty list (simulates AI returning nothing).
    side_effect:
        Optional callable invoked with *(batch, config)* before returning
        ``fixes``.  Use to assert inputs or count calls::

            calls = []
            mock = MockAIProvider(side_effect=lambda b, c: calls.append(len(b)))
    """

    def __init__(
        self,
        fixes: list[dict] | None = None,
        *,
        side_effect: Callable[[list[dict], dict], None] | None = None,
    ) -> None:
        self._fixes: list[dict] = fixes or []
        self._side_effect = side_effect
        self.call_count = 0
        self.last_batch: list[dict] = []
        self.last_config: dict = {}

    def review_batch(self, batch: list[dict], config: dict) -> list[dict]:
        self.call_count += 1
        self.last_batch = batch
        self.last_config = config
        if self._side_effect is not None:
            self._side_effect(batch, config)
        # Filter to only return fixes whose key is present in batch
        batch_keys = {item["key"] for item in batch}
        return [f for f in self._fixes if f.get("key") in batch_keys]
