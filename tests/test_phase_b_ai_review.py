from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.audits.ai_review import run_stage


def _make_runtime(tmp_path: Path):
    """Build a minimal runtime mock for ai_review tests."""
    runtime = MagicMock()
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
    (tmp_path / "results").mkdir(parents=True, exist_ok=True)
    runtime.glossary_file.write_text('{"terms": []}')
    return runtime


def _make_options():
    """Build a minimal options mock for ai_review tests (AI enabled)."""
    options = MagicMock()
    options.ai_review.enabled = True
    options.ai_review.provider = "test"
    options.ai_review.model = "test-model"
    options.ai_review.api_key_env = "OPENAI_API_KEY"
    options.ai_review.batch_size = 50
    options.ai_review.translate_missing = False
    options.ai_review.short_label_threshold = 3
    options.write_reports = False
    options.audit_rules.role_identifiers = []
    options.audit_rules.entity_whitelist = []
    return options


def _make_stub_provider(expected_batches: list) -> MagicMock:
    """Build a stub AI provider that returns controlled review_batch output."""
    provider = MagicMock()
    provider.review_batch.side_effect = expected_batches
    return provider


def test_ai_review_run_stage_with_paired_injected_state(tmp_path: Path):
    """
    Prove that ai_review can successfully operate from paired pre-hydrated 
    canonical state when injected, avoiding raw internal file reads entirely.

    The probe: locale files contain 'bad_key' but we only inject 'qa_key'.
    If the audit reads from files, it would see 'bad_key'; under injected state,
    only 'qa_key' appears in the prompt inputs.
    """
    runtime = _make_runtime(tmp_path)
    options = _make_options()

    # Locale files contain ONLY bad_key — must NOT be read by ai_review
    runtime.en_file.write_text('{"bad_key": "Should not be read"}')
    runtime.ar_file.write_text('{"bad_key": "يجب ألا يُقرأ"}')

    # Pre-hydrated paired state — only qa_key exists here
    canonical_en_data = {"qa_key": "This is a quality assurance sentence."}
    canonical_ar_data = {"qa_key": "هذه جملة ضمان الجودة."}

    # A previous issue referencing qa_key triggers the AI review
    previous_issues = [
        {
            "key": "qa_key",
            "issue_type": "ar_qc",
            "message": "Possible quality issue detected.",
            "severity": "warning",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
    ]

    # Stub provider captures what was built and passed to review_batch
    captured_batches = []

    def capture_review_batch(batch, config, glossary=None):
        captured_batches.append(batch)
        return []  # No AI fixes — we're just proving context is built correctly

    stub_provider = MagicMock()
    stub_provider.review_batch.side_effect = capture_review_batch

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        issues = run_stage(
            runtime, options,
            ai_provider=stub_provider,
            previous_issues=previous_issues,
            en_data=canonical_en_data,
            ar_data=canonical_ar_data,
        )

    assert isinstance(issues, list)

    # Verify the batch was built from injected state, not from files
    assert len(captured_batches) == 1
    batch = captured_batches[0]
    batch_keys = {item["key"] for item in batch}
    assert "bad_key" not in batch_keys, "ai_review must not read file locale state when injected state is provided"
    assert "qa_key" in batch_keys, "ai_review must use injected state to build batch items"

    # Verify that the batch item was built with injected EN/AR live values
    qa_item = next(item for item in batch if item["key"] == "qa_key")
    assert qa_item["source"] == "This is a quality assurance sentence."
    assert qa_item["current_translation"] == "هذه جملة ضمان الجودة."


def test_ai_review_fallback_logs_warn(tmp_path: Path, caplog):
    """
    Ensure the narrow backwards compatibility fallback works but explicitly warns
    when invoked lacking paired injected state.
    """
    runtime = _make_runtime(tmp_path)
    options = _make_options()

    # It must fallback to loading these files if paired data isn't supplied
    runtime.en_file.write_text('{"fallback_key": "Fallback test sentence."}')
    runtime.ar_file.write_text('{"fallback_key": "جملة اختبار احتياطية."}')

    previous_issues = [
        {
            "key": "fallback_key",
            "issue_type": "ar_qc",
            "message": "Quality issue via fallback path.",
            "severity": "warning",
            "decision": {"route": "ai_review", "confidence": 0.8, "risk": "low"},
        }
    ]

    captured_batches = []

    def capture_review_batch(batch, config, glossary=None):
        captured_batches.append(batch)
        return []

    stub_provider = MagicMock()
    stub_provider.review_batch.side_effect = capture_review_batch

    with patch("l10n_audit.core.validators.validate_ai_config", return_value={"api_key": "test"}):
        issues = run_stage(
            runtime, options,
            ai_provider=stub_provider,
            previous_issues=previous_issues,
            # Deliberately NOT passing en_data / ar_data → triggers fallback
        )

    assert isinstance(issues, list)
    assert "Deprecation: ai_review invoked without paired canonical state" in caplog.text

    # And the fallback must still work — fallback_key must appear in the batch
    assert len(captured_batches) == 1
    batch_keys = {item["key"] for item in captured_batches[0]}
    assert "fallback_key" in batch_keys
