from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.audits.ai_review import run_stage
from l10n_audit.core.ai_http_provider import HttpAIProvider


def _runtime(tmp_path: Path) -> MagicMock:
    runtime = MagicMock()
    runtime.config = {"decision_engine": {"respect_routing": True}}
    runtime.config_dir = tmp_path
    runtime.en_file = tmp_path / "en.json"
    runtime.ar_file = tmp_path / "ar.json"
    runtime.results_dir = tmp_path / "results"
    runtime.source_locale = "en"
    runtime.target_locales = ("ar",)
    runtime.metadata = {}
    runtime.results_dir.mkdir(parents=True, exist_ok=True)
    return runtime


def _options() -> MagicMock:
    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "test"
    options.ai_review.model = "test-model"
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.batch_size = 50
    options.ai_review.translate_missing = False
    options.ai_review.short_label_threshold = 3
    options.write_reports = False
    return options


def test_invocation_control_skips_deterministic_fix(tmp_path: Path):
    runtime = _runtime(tmp_path)
    options = _options()
    issues = [
        {
            "key": "home.title",
            "issue_type": "whitespace",
            "message": "Trim leading/trailing spaces",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
            "classification": "auto_safe",
        }
    ]
    en_data = {"home.title": "Home"}
    ar_data = {"home.title": " الرئيسية "}
    provider = MagicMock()
    provider.review_batch.return_value = []

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    provider.review_batch.assert_not_called()


def test_invocation_control_skips_short_ambiguous_without_context(tmp_path: Path):
    runtime = _runtime(tmp_path)
    options = _options()
    issues = [
        {
            "key": "cta.save",
            "issue_type": "semantic_mismatch",
            "message": "Potential meaning drift.",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
    ]
    en_data = {"cta.save": "Save now"}
    ar_data = {"cta.save": "حفظ"}
    provider = MagicMock()
    provider.review_batch.return_value = []

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    provider.review_batch.assert_not_called()


def test_invocation_control_calls_ai_for_missing_translation(tmp_path: Path):
    runtime = _runtime(tmp_path)
    options = _options()
    options.ai_review.translate_missing = True
    issues = [
        {
            "key": "profile.name",
            "issue_type": "empty_ar",
            "message": "Arabic translation is empty.",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
    ]
    en_data = {"profile.name": "Profile name"}
    ar_data = {"profile.name": ""}
    provider = MagicMock()
    provider.review_batch.return_value = []

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    provider.review_batch.assert_called_once()


def test_input_payload_contract_includes_required_fields(tmp_path: Path):
    runtime = _runtime(tmp_path)
    options = _options()
    (runtime.config_dir / "glossary.json").write_text(
        '{"terms":[{"term_en":"Wallet","approved_ar":"المحفظة","definition":"finance"}]}',
        encoding="utf-8",
    )
    issues = [
        {
            "key": "profile.wallet_title",
            "issue_type": "semantic_mismatch",
            "message": "Needs contextual correction.",
            "context": "Profile screen title",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
    ]
    en_data = {"profile.wallet_title": "Wallet for {name}"}
    ar_data = {"profile.wallet_title": "محفظة"}
    captured_batches = []

    def _capture(batch, *_args, **_kwargs):
        captured_batches.append(batch)
        return []

    provider = MagicMock()
    provider.review_batch.side_effect = _capture

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        run_stage(runtime, options, ai_provider=provider, previous_issues=issues, en_data=en_data, ar_data=ar_data)

    assert len(captured_batches) == 1
    payload = captured_batches[0][0]
    assert payload["key"] == "profile.wallet_title"
    assert payload["source_text"] == "Wallet for {name}"
    assert payload["locale"] == "ar"
    assert "{name}" in payload["placeholders"]
    assert payload["glossary"] == {"Wallet": "المحفظة"}


def test_http_provider_prompt_wires_glossary_and_context():
    provider = HttpAIProvider()
    batch = [
        {
            "key": "profile.wallet_title",
            "source_text": "Wallet for {name}",
            "current_text": "محفظة",
            "locale": "ar",
            "placeholders": ["{name}"],
            "context": "Profile screen title",
            "glossary": {"Wallet": "المحفظة"},
            "source": "Wallet for {name}",
            "current_translation": "محفظة",
            "identified_issue": "semantic mismatch",
        }
    ]
    prompts = []

    def _fake_request(prompt, *_args, **_kwargs):
        prompts.append(prompt)
        return {"translated_text": "المحفظة لـ {name}"}

    with patch("l10n_audit.core.ai_http_provider.request_ai_review", side_effect=_fake_request):
        fixes = provider.review_batch(batch, {"api_key": "test"}, glossary={})

    assert fixes and fixes[0]["suggestion"] == "المحفظة لـ {name}"
    assert prompts, "Expected prompt to be generated and sent."
    prompt = prompts[0]
    assert "Wallet for {name}" in prompt
    assert "TARGET LOCALE" in prompt and "ar" in prompt
    assert "Profile screen title" in prompt
    assert "Wallet" in prompt and "المحفظة" in prompt

