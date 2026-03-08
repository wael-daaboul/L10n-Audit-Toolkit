# Project Overview

## Purpose

L10n Audit Toolkit is a repository-oriented localization QA and translation validation toolkit. It scans locale sources and application code, produces audit findings, generates safe fix plans, and supports a review queue for fixes that require human approval.

The current implementation is centered on English source content and Arabic target review workflows, with support for several common JSON- and Laravel-based localization layouts.

## Pipeline Summary

The toolkit follows a staged pipeline:

1. Load project configuration and detect or confirm a supported project profile.
2. Load locale data from JSON or Laravel PHP sources.
3. Scan source code for translation key usage.
4. Run audit modules on locale content and cross-locale consistency.
5. Normalize findings and aggregate them into report outputs.
6. Generate safe fix candidates and a review queue.
7. Apply approved fixes and export final locale outputs.

## Repository Structure

### `audits/`

Contains audit modules that inspect locale files and usage data. These modules emit structured findings that later feed the report and fix pipeline.

Examples:

- localization usage and missing key checks
- placeholder validation
- terminology and glossary checks
- ICU message validation
- English and Arabic locale quality checks

### `core/`

Contains the shared runtime and infrastructure used by the rest of the project.

Typical responsibilities:

- config loading and path resolution
- project profile detection
- locale loading and exporting
- report helpers
- usage scanning
- schema validation
- XLSX and JSON utility functions

### `fixes/`

Contains the fix application pipeline.

- `apply_safe_fixes.py`: generates and applies conservative auto-safe changes
- `apply_review_fixes.py`: applies human-approved review queue changes after integrity checks

### `reports/`

Builds final aggregated outputs from individual audit results.

Typical outputs include:

- final Markdown dashboard
- normalized issue JSON
- XLSX review queue
- final report JSON

### `schemas/`

JSON schemas for project configuration and generated artifacts. These help keep config and output contracts explicit and testable.

### `config/`

Contains:

- project configuration
- built-in project profile definitions

This directory drives path discovery, profile selection, locale locations, and usage pattern selection.

### `bin/`

Shell entry points for common workflows.

- `l10n_audit.sh`: basic localization usage audit
- `run_all_audits.sh`: multi-stage orchestration script for the full audit workflow

### `examples/`

Framework-oriented sample layouts and documentation for supported project styles. These examples are intended to help users understand expected repository structure and toolkit configuration.

### `tests/`

Regression coverage for loaders, exporters, audits, fix safety, report generation, and schema validation.

## How Audits and Fixes Interact

Audit modules only report findings. They do not directly rewrite locale sources.

The fix pipeline is separate:

- deterministic low-risk changes can become auto-safe fix candidates
- context-sensitive or risky changes are routed to the review queue
- approved fixes are only applied after integrity validation against the source snapshot

This separation keeps translation data integrity higher than aggressive auto-correction.

## Key Terms

- `audit finding`: a single issue emitted by an audit module
- `violation`: a rule-specific finding, commonly used by terminology checks
- `fix plan`: candidate changes generated for safe or reviewed application
- `review queue`: XLSX sheet for human approval of risky changes
- `approved fix`: a review-queue row explicitly marked for application
- `final locale`: reviewed locale output written after approved fixes are applied

These terms are used consistently across the repository documentation and generated outputs.
