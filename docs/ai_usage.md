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
- **Consolidated Report:** `Results/final/final_audit_report.md`.

AI suggestions are **never automatically applied**. They must be approved in the review queue before being injected into the final locale file.
