# Audit Modules

## Purpose

This page explains the major audit modules included in L10n Audit Toolkit and how they contribute to translation QA, placeholder validation, terminology audit, and localization review.

## Core Audit Modules

### `placeholder_audit`

Checks placeholder consistency between locales.

Typical findings:

- missing placeholders
- renamed placeholders
- placeholder count mismatches
- placeholder format mismatches
- order mismatches

Use this audit when placeholder validation is a release-critical requirement.

### `terminology_audit`

Validates target-locale terminology against a project glossary.

Typical findings:

- forbidden term usage
- hard violations
- context-sensitive term conflicts
- soft terminology drift

Use this audit to enforce approved product vocabulary and glossary terms.

### `icu_message_audit`

Validates ICU-like plural, select, and selectordinal message structures.

Typical findings:

- ICU syntax errors
- missing required branches
- branch mismatches between locales
- placeholder mismatches inside ICU branches
- suspicious structural differences

This audit is review-oriented. ICU logic is not rewritten automatically.

### `en_locale_qc`

Runs deterministic quality checks on English source locale content.

Typical findings:

- whitespace and spacing issues
- grammar and style issues
- capitalization issues
- key naming mistakes
- placeholder mismatches against the target locale

This audit is conservative around technical strings and formatting-sensitive content.

### `ar_locale_qc`

Runs deterministic Arabic locale quality checks with context-aware review support.

Typical findings:

- spacing and punctuation formatting issues
- bracket and slash spacing issues
- forbidden terminology
- suspicious literal translation patterns
- context-sensitive review findings

This audit prefers review-required output over risky automatic rewriting.

### `ar_semantic_qc`

Runs review-only Arabic semantic checks and proposes conservative candidate rewrites for sentence-level meaning loss.

Typical findings:

- sentence shape mismatch between English and Arabic
- message-versus-label collapse in Arabic UI text
- possible action meaning loss
- context-sensitive role/entity ambiguity kept in manual review

This module does not auto-apply changes. Its candidate suggestions are intended for the review queue only.

## Supporting Audit Modules

### `l10n_audit_pro`

Extended localization usage and missing-key audit logic. This module complements the basic code-usage scan and feeds aggregated reporting.

### `en_grammar_audit`

Grammar-oriented English review using local LanguageTool discovery and fallback behavior where configured.

## How Modules Fit Together

The toolkit is modular:

- each audit emits structured findings
- findings are normalized and aggregated later
- safe fixes are generated from deterministic low-risk findings only
- review-required findings move into the review queue

This separation keeps audit logic independent from fix application logic.

## Available Stages (`l10n-audit run --stage <STAGE>`)

- `fast`: Localizations + AR QC + Placeholders + Terminology + Aggregation.
- `full`: `fast` + ICU Audit + Grammar + Full Aggregation.
- `grammar`: Runs `audits.en_grammar_audit`
- `terminology`: Runs `audits.terminology_audit`
- `placeholders`: Runs `audits.placeholder_audit`
- `ar-qc`: Runs `audits.ar_locale_qc`
- `ar-semantic`: Runs `audits.ar_semantic_qc`
- `icu`: Runs `audits.icu_message_audit`
- `reports`: Runs `reports.report_aggregator`
- `autofix`: Runs `fixes.apply_safe_fixes`
- `ai-review`: Runs `audits.ai_review`

### Legacy Scripts vs Python Modules
If you are developing modules or need raw Python execution, you can bypass the CLI by exporting `L10N_AUDIT_CONFIG`:

```bash
# Recommended CLI approach
l10n-audit run --stage terminology

# Raw Developer approach
python -m audits.terminology_audit
```
Note: Legacy bash scripts (`bin/run_all_audits.sh` and `bin/l10n_audit.sh`) are maintained for backward compatibility but using the Python modules or the CLI is the official path.
