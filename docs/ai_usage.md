# AI-Assisted Translation Review

The L10n Audit Toolkit integrates with Large Language Models (LLMs) to provide context-aware translation reviews, detect subtle meaning loss, and suggest natural Arabic phrasing.

## How it Works
The AI review stage (`ai-review`) sends the following context to the model:
1. The translation Key.
2. The English source value.
3. The current Arabic translation.
4. (Optional) Inferred UI context from code usage.

The model then evaluates the translation and provides standardized suggestions or confirms the quality.

## Basic Usage

To run the AI review, you must use the `--ai-enabled` flag and specify a model.

```bash
l10n-audit run --stage ai-review \
  --ai-enabled \
  --ai-api-key "your-api-key" \
  --ai-model "openai/gpt-4o-mini"
```

## Advanced Configuration

### Using Custom API Endpoints (OpenRouter, local LLMs)
If you are using OpenRouter or a local instance of an LLM (like Ollama or vLLM), use the `--ai-api-base` flag.

```bash
l10n-audit run --stage ai-review \
  --ai-enabled \
  --ai-api-base "https://openrouter.ai/api/v1" \
  --ai-model "anthropic/claude-3-haiku" \
  --ai-api-key "your-openrouter-key"
```

### Environment Variables
For security, we recommend setting your API keys in your environment instead of passing them as command-line arguments.

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
# Then run without --ai-api-key
l10n-audit run --stage ai-review --ai-enabled --ai-model "openai/gpt-4o"
```

## CLI Options Reference

| Option | Description | Example |
| :--- | :--- | :--- |
| `--ai-enabled` | Master toggle to enable AI features. | Required for AI stages |
| `--ai-api-base` | Custom Base URL for OpenAI-compatible APIs. | `https://openrouter.ai/api/v1` |
| `--ai-api-key` | API Key for the provider. | `sk-...` |
| `--ai-model` | The model identifier to use. | `gpt-4o`, `meta-llama/llama-3-70b` |

## Results & Review
AI suggestions are written to the standard results directory:
- **XLSX Review Queue:** `Results/review/review_queue.xlsx` (Look for `ai_review` in the `issue_type` column).
- **Frozen Execution Workbook:** `Results/review/review_final.xlsx` after running `l10n-audit prepare-apply`.
- **Consolidated Report:** `Results/final/final_audit_report.md`.

AI suggestions flow only into `review_queue.xlsx`. They never flow directly into `review_final.xlsx`.

AI suggestions are **never automatically applied**. They must be reviewed in `review_queue.xlsx`, frozen by `prepare-apply`, and then executed from `review_final.xlsx`.

The adaptive config workflow is separate:

`generate-adaptation-report -> generate-manifest -> review-manifest -> apply-manifest`

AI review suggestions do not bypass this chain and do not write directly to manifest artifacts.

---

## Provider Resilience

The AI review stage handles provider failures gracefully without crashing the pipeline:

- **Automatic retry with bounded backoff:** Transient errors (timeouts, connection resets) are retried with exponential backoff capped at a configurable maximum. Rate-limited responses use a stronger backoff multiplier.
- **Rate-limit circuit breaker:** Repeated throttling across batches triggers an early-stop with a clear CLI message. Previously processed batches are preserved.
- **Graceful degradation:** If the provider fails persistently, AI review is skipped for remaining batches. The rest of the audit pipeline continues normally.
- **No crash on provider failure:** The toolkit never exits with an error solely due to AI provider unavailability.

The CLI final summary always reports the AI review outcome (completed, degraded, or skipped).

---

## Debug Mode

Set the environment variable `L10N_AUDIT_DEBUG_AI=1` to enable AI debug mode:

```bash
export L10N_AUDIT_DEBUG_AI=1
l10n-audit run --stage ai-review --ai-enabled --ai-model "openai/gpt-4o-mini"
```

In debug mode:
- Raw LiteLLM and provider stdout/stderr output is preserved (not suppressed).
- Detailed per-attempt provider error information is logged.
- Fallback reason codes are emitted for every skipped or degraded decision.

In normal mode (default):
- LiteLLM help/provider spam is suppressed to keep toolkit progress output readable.
- Toolkit-owned log lines remain fully visible.
- Provider errors are logged at `DEBUG` level.

---

## Canonical Source Guard

The canonical source guard (`L10N_AUDIT_CANONICAL_SOURCE_GUARD_DISABLE`) prevents source-identity drift during AI review. It is **enabled by default** in v1.7.1.

To disable it (not recommended for production):

```bash
export L10N_AUDIT_CANONICAL_SOURCE_GUARD_DISABLE=1
```
