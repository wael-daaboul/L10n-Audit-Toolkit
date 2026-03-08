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

## Running Individual Modules

Examples:

```bash
python -m audits.placeholder_audit
python -m audits.terminology_audit
python -m audits.icu_message_audit
python -m audits.en_locale_qc
python -m audits.ar_locale_qc
```

For most users, `./bin/run_all_audits.sh` is the preferred entry point because it runs modules in a predictable sequence and writes standard outputs under `Results/`.
