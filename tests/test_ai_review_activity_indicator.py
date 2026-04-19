import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.ai.provider import AIProviderError
from l10n_audit.audits import ai_review as ai_review_stage
from l10n_audit.audits.ai_review import run_stage


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


def _make_options(*, batch_size: int = 1, max_consecutive_failures: int = 2, indicator_interval: float = 0.01):
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
    options.ai_review.activity_indicator_enabled = True
    options.ai_review.activity_indicator_interval_seconds = indicator_interval
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


def test_activity_indicator_starts_during_provider_wait(tmp_path, capsys, monkeypatch):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, indicator_interval=0.01)
    provider = MagicMock()

    def _slow_batch(*_args, **_kwargs):
        time.sleep(0.12)
        return []

    provider.review_batch.side_effect = _slow_batch
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)
    spinner_frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert "AI Review: processing 1 batch(es)..." in output
    assert any(frame in output for frame in spinner_frames)


def test_activity_indicator_stop_cleanup_on_success(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, indicator_interval=0.01)
    provider = MagicMock()
    provider.review_batch.return_value = []
    issues = _make_issues(2)
    en_data, ar_data = _make_locale_state(2)
    starts: list[int] = []
    stops: list[int] = []

    class _RecorderIndicator:
        def __init__(self, *, batch_index, total_batches, enabled, interval_seconds, stream=None):
            self.enabled = enabled

        def start(self):
            starts.append(1)

        def stop(self):
            stops.append(1)

    monkeypatch.setattr(ai_review_stage, "_AIReviewWaitIndicator", _RecorderIndicator)
    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert len(starts) == 2
    assert len(stops) == 2


def test_activity_indicator_stop_cleanup_on_degraded_exit(tmp_path, monkeypatch, capsys):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=1, indicator_interval=0.01)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError("provider_timeout", "timeout")
    issues = _make_issues(2)
    en_data, ar_data = _make_locale_state(2)
    starts: list[int] = []
    stops: list[int] = []

    class _RecorderIndicator:
        def __init__(self, *, batch_index, total_batches, enabled, interval_seconds, stream=None):
            self.enabled = enabled

        def start(self):
            starts.append(1)

        def stop(self):
            stops.append(1)

    monkeypatch.setattr(ai_review_stage, "_AIReviewWaitIndicator", _RecorderIndicator)
    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert len(starts) == 1
    assert len(stops) == 1
    assert "AI Review: stopping after 1 consecutive provider failures" in output


def test_activity_indicator_keeps_cli_output_readable(tmp_path, capsys):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, max_consecutive_failures=1, indicator_interval=0.01)
    provider = MagicMock()
    provider.review_batch.side_effect = AIProviderError("provider_timeout", "timeout")
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    output = capsys.readouterr().out
    assert "AI Review: processing 1 batch(es)..." in output
    assert "AI Review: batch 1/1 failed [provider_timeout]" in output
    assert "AI Review: provider failures detected; continuing run without AI suggestions." in output


def test_ai_review_logic_regression_guard_with_indicator_enabled(tmp_path):
    runtime = _make_runtime(tmp_path)
    options = _make_options(batch_size=1, indicator_interval=0.01)
    provider = MagicMock()
    provider.review_batch.return_value = [
        {"key": "home.title.0", "suggestion": "ترجمة محسنة", "reason": "AI"},
    ]
    issues = _make_issues(1)
    en_data, ar_data = _make_locale_state(1)

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        result = run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert "home.title.0" in _issue_keys(result)
    assert runtime.metadata["ai_review_status"]["status"] == "ok"
