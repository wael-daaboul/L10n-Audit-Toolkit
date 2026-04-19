import logging
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from l10n_audit.ai.provider import AIProviderError, request_ai_review_litellm
from l10n_audit.audits.ai_review import run_stage


def _provider_json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return response


def _make_runtime(tmp_path: Path):
    runtime = MagicMock()
    runtime.config = {"decision_engine": {"respect_routing": True}}
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.glossary_file = tmp_path / "glossary.json"
    runtime.results_dir = tmp_path / "results"
    runtime.code_dirs = []
    runtime.usage_patterns = {}
    runtime.allowed_extensions = []
    runtime.project_profile = "default"
    runtime.locale_format = "json"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.metadata = {}
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    runtime.glossary_file.write_text('{"terms": []}')
    return runtime


def _make_options(batch_size: int = 1, max_consecutive_failures: int = 2):
    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "test"
    options.ai_review.model = "test-model"
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.batch_size = batch_size
    options.ai_review.translate_missing = False
    options.ai_review.short_label_threshold = 3
    options.ai_review.request_timeout_seconds = 5
    options.ai_review.max_consecutive_failures = max_consecutive_failures
    options.write_reports = False
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []
    return options


def _make_issues(count: int) -> list[dict]:
    return [
        {
            "key": f"home.title.{i}",
            "issue_type": "ar_qc",
            "message": "Possible semantic issue.",
            "context": "Screen title shown in settings dashboard header",
            "severity": "warning",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
        for i in range(count)
    ]


def _make_locale_state(count: int) -> tuple[dict, dict]:
    en_data = {f"home.title.{i}": f"This is a longer English source text {i}" for i in range(count)}
    ar_data = {f"home.title.{i}": f"نص عربي حالي {i}" for i in range(count)}
    return en_data, ar_data


def _issue_keys(issues) -> set[str]:
    keys = set()
    for issue in issues:
        if hasattr(issue, "to_dict"):
            keys.add(issue.to_dict().get("key"))
        else:
            keys.add(issue.get("key"))
    return {k for k in keys if k}


def test_timeout_is_normalized_to_provider_timeout():
    with patch("l10n_audit.ai.provider.litellm.completion", side_effect=TimeoutError("read timed out")):
        with pytest.raises(AIProviderError) as exc_info:
            request_ai_review_litellm("prompt", {"api_key": "k", "model": "m", "request_timeout_seconds": 1}, max_retries=1)
    assert exc_info.value.category == "provider_timeout"


def test_ai_batch_provider_failure_gracefully_degrades_without_crash(tmp_path):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=2)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError("provider_timeout", "timeout")
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        result = run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert result == []


def test_circuit_breaker_stops_after_max_consecutive_provider_failures(tmp_path, capsys):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=2)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError("provider_connection_error", "connect failed")
    issues = _make_issues(4)
    en_data, ar_data = _make_locale_state(4)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert provider.review_batch.call_count == 2
    assert "AI Review: stopping after 2 consecutive provider failures" in output


def test_partial_success_is_preserved_before_circuit_breaker_stops(tmp_path):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=2)
    provider = MagicMock()
    provider.review_batch.side_effect = [
        [{"key": "home.title.0", "suggestion": "ترجمة محسنة", "reason": "AI"}],
        AIProviderError("provider_rate_limited", "rate limited"),
        AIProviderError("provider_timeout", "timeout"),
    ]
    issues = _make_issues(3)
    en_data, ar_data = _make_locale_state(3)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        result = run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert "home.title.0" in _issue_keys(result)


def test_cli_status_is_concise_in_normal_mode(tmp_path, capsys, caplog, monkeypatch):
    monkeypatch.delenv("L10N_AUDIT_DEBUG_AI", raising=False)
    caplog.set_level(logging.DEBUG)
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=1)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError(
        "provider_timeout",
        "timeout",
        details={"error": "socket read timed out"},
    )
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert "AI Review: batch 1/1 failed [provider_timeout]" in output
    assert "socket read timed out" not in output


def test_debug_mode_keeps_provider_details_and_emits_fallback_reason(tmp_path, caplog, monkeypatch):
    monkeypatch.setenv("L10N_AUDIT_DEBUG_AI", "1")
    caplog.set_level(logging.DEBUG)
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=1)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError(
        "provider_timeout",
        "timeout",
        details={"error": "socket read timed out"},
    )
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert "provider_timeout" in caplog.text
    assert "socket read timed out" in caplog.text


def test_rate_limited_progress_line_includes_attempts(tmp_path, capsys):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=1)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError(
        "provider_rate_limited",
        "rate limited",
        details={"attempt": 2, "max_attempts": 3},
    )
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert "AI Review: batch 1/1 rate limited — applying backoff (attempt 2/3)" in output
    assert "AI Review: batch 1/1 failed [provider_rate_limited]" in output


@patch("l10n_audit.ai.provider.time.sleep")
def test_provider_retry_uses_bounded_exponential_backoff(mock_sleep):
    completion_side_effects = [
        RuntimeError("connection reset by peer"),
        RuntimeError("connection reset by peer"),
        _provider_json_response({"fixes": []}),
    ]
    with patch("l10n_audit.ai.provider.litellm.completion", side_effect=completion_side_effects):
        response = request_ai_review_litellm(
            "prompt",
            {"api_key": "k", "model": "m"},
            max_retries=3,
        )
    assert response == {"fixes": []}
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0].args[0] == 1.0
    assert mock_sleep.call_args_list[1].args[0] == 2.0


@patch("l10n_audit.ai.provider.time.sleep")
def test_rate_limited_retry_uses_stronger_backoff(mock_sleep):
    completion_side_effects = [
        RuntimeError("rate limit exceeded"),
        RuntimeError("rate limit exceeded"),
        RuntimeError("rate limit exceeded"),
    ]
    with patch("l10n_audit.ai.provider.litellm.completion", side_effect=completion_side_effects):
        with pytest.raises(AIProviderError) as exc_info:
            request_ai_review_litellm(
                "prompt",
                {"api_key": "k", "model": "m"},
                max_retries=3,
            )
    assert exc_info.value.category == "provider_rate_limited"
    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0].args[0] == 2.0
    assert mock_sleep.call_args_list[1].args[0] == 4.0


@patch("l10n_audit.ai.provider.time.sleep")
def test_provider_retry_backoff_is_capped(mock_sleep):
    completion_side_effects = [
        RuntimeError("connection reset by peer"),
        RuntimeError("connection reset by peer"),
        RuntimeError("connection reset by peer"),
        _provider_json_response({"fixes": []}),
    ]
    with patch("l10n_audit.ai.provider.litellm.completion", side_effect=completion_side_effects):
        request_ai_review_litellm(
            "prompt",
            {
                "api_key": "k",
                "model": "m",
                "provider_retry_backoff_max_seconds": 2,
            },
            max_retries=4,
        )
    assert [call.args[0] for call in mock_sleep.call_args_list] == [1.0, 2.0, 2.0]


@patch("l10n_audit.ai.provider.time.sleep")
def test_rate_limited_backoff_is_capped(mock_sleep):
    completion_side_effects = [
        RuntimeError("rate limit exceeded"),
        RuntimeError("rate limit exceeded"),
        RuntimeError("rate limit exceeded"),
        _provider_json_response({"fixes": []}),
    ]
    with patch("l10n_audit.ai.provider.litellm.completion", side_effect=completion_side_effects):
        request_ai_review_litellm(
            "prompt",
            {
                "api_key": "k",
                "model": "m",
                "provider_rate_limit_backoff_max_seconds": 3,
            },
            max_retries=4,
        )
    assert [call.args[0] for call in mock_sleep.call_args_list] == [2.0, 3.0, 3.0]


@patch("time.sleep")
def test_inter_batch_delay_uses_deterministic_spacing(mock_sleep, tmp_path):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=3)
    provider = MagicMock()
    provider.review_batch.return_value = []
    issues = _make_issues(3)
    en_data, ar_data = _make_locale_state(3)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert mock_sleep.call_count == 2
    assert mock_sleep.call_args_list[0].args[0] == 0.5
    assert mock_sleep.call_args_list[1].args[0] == 0.5


def test_repeated_rate_limits_stop_remaining_batches_early(tmp_path, capsys):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=5)
    provider = MagicMock()
    provider.review_batch.side_effect = [
        AIProviderError("provider_rate_limited", "rate limited", details={"attempt": 2, "max_attempts": 3}),
        AIProviderError("provider_rate_limited", "rate limited", details={"attempt": 3, "max_attempts": 3}),
        [],
    ]
    issues = _make_issues(4)
    en_data, ar_data = _make_locale_state(4)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert provider.review_batch.call_count == 2
    assert "AI Review: rate limited — stopping remaining batches after repeated provider throttling" in output
    usage = runtime.metadata["ai_review_status"]["provider_usage"]
    assert usage["requests_sent"] == 2
    assert usage["rate_limit_failures"] == 2
    assert usage["retries_attempted"] == 3
