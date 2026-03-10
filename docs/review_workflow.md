# Review Workflow

## Purpose

L10n Audit Toolkit separates deterministic fixes from human-reviewed fixes. This document explains the fix plan, review queue, approved fixes, and final locale outputs.

## Workflow Summary

1. Run audits.
2. Aggregate findings into final reports.
3. Generate safe fix candidates.
4. Review risky changes in the XLSX review queue.
5. Apply approved fixes with integrity checks.
6. export the final locale.

## 1. Safe Auto-fixes
The toolkit can automatically fix non-destructive formatting issues:
```bash
l10n-audit run --stage autofix
```
*Equivalant to:* `python -m fixes.apply_safe_fixes`

## 2. Manual Reviews Queue
When a `review_queue.xlsx` is generated, translators can mark rows as "Approved". To apply these approved changes directly to your `ar.json`:

```bash
python -m fixes.apply_review_fixes --review-queue Results/review/review_queue.xlsx
```
*Why?* It validates hashes to ensure source files haven't changed before injecting the translator's new text.

## 3. AI-Assisted Review
Generate review suggestions using language models:
```bash
l10n-audit run --stage ai-review \
  --ai-enabled \
  --ai-api-base "https://api.openai.com/v1" \
  --ai-model "gpt-4" \
  --ai-api-key "sk-..." 
```
Options available:
- `--ai-enabled`: Master toggle for AI execution.
- `--ai-api-base`: Target endpoint (essential for OpenRouter / local LLMs).
- `--ai-api-key`: API key (Can also be read from environment variables).
- `--ai-model`: The model identifier.
