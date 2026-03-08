# Output Reports

## Purpose

This document describes the generated report files and how they fit into the localization audit workflow.

## Output Locations

### `Results/per_tool/`

Raw outputs from individual audit modules.

Examples:

- placeholder audit JSON, CSV, XLSX
- terminology audit JSON
- locale QA reports
- ICU audit reports

### `Results/normalized/`

Normalized machine-readable issue collections used by the report aggregator and downstream automation.

### `Results/review/`

Human-review artifacts.

- `review_queue.xlsx`
- `review_queue.json`

### `Results/fixes/`

Safe-fix outputs.

- `fix_plan.json`
- `fix_plan.xlsx`
- `safe_fixes_applied_report.json`
- intermediate fixed locale candidates

### `Results/final/`

Aggregated reporting outputs.

- final Markdown dashboard
- final report JSON
- normalized issue summary

### `Results/final_locale/`

Final locale outputs after approved fixes are applied.

## Report Types

### JSON Reports

Used for:

- machine-readable findings
- downstream tooling
- schema validation
- CI artifact inspection

### XLSX Reports

Used for:

- reviewer-friendly audit review
- fix plan browsing
- manual approval workflow

### Markdown Reports

Used for:

- dashboard-style summaries
- prioritized issue review
- repository-friendly human-readable outputs

## Common Artifacts

### Final audit dashboard

- `Results/final/final_audit_report.md`

Contains:

- total issue counts
- review-required counts
- prioritized findings
- output references

### Review queue

- `Results/review/review_queue.xlsx`

Contains:

- reviewable findings
- current locale value
- suggested fix
- integrity metadata

### Safe fix plan

- `Results/fixes/fix_plan.json`

Contains:

- candidate changes
- classification
- provenance

### Review fix report

- `Results/final_locale/review_fixes_report.json`

Contains:

- applied fixes
- skipped fixes
- integrity-failure reasons

## How To Use The Outputs

- start with the final Markdown dashboard
- inspect per-tool reports for module-specific detail
- use the review queue for approved fixes
- keep JSON artifacts for CI or archival use

When troubleshooting a change, compare the original per-tool finding, the fix plan entry, and the final review-fix report.
