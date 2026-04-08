# System Overview

L10n Audit Toolkit is designed to provide a robust, repeatable, and safe localization pipeline. This document explains the architecture, data flow, and the core philosophy behind the toolkit.

## Pipeline Stages

The toolkit operates in a strictly ordered pipeline to guarantee data integrity:

1. **Isolation (`init`)**: Project locales are loaded and safely copied into a `.l10n-audit/workspace/` environment. Your original files are never touched during the audit.
2. **Execution (`run`)**: Audit modules (Fast, Full, AI) run in parallel over the isolated workspace files, generating raw findings.
3. **Aggregation**: Raw findings are gathered, deductively merged, and written to the central master state.
4. **Projection**: The master state is projected into the editable human workspace `review_queue.xlsx` and the standard Markdown dashboard.
5. **Freeze (`prepare-apply`)**: Approved rows are validated and frozen into `review_final.xlsx`.
6. **Execution (`apply`)**: The toolkit reads only `review_final.xlsx`, the frozen execution contract.
7. **Reconciliation**: Approved changes are generated as `.fix` files (e.g., `en.fix.json` or `ar.fix.php`). The toolkit reconciles these back to the master state, ensuring a perfect audit trail.

The adaptive configuration path is separate and explicit:

1. `generate-adaptation-report`
2. `generate-manifest`
3. `review-manifest`
4. `apply-manifest`

This chain never runs automatically inside `run`.

| File | Role |
| :--- | :--- |
| `review_queue.xlsx` | Editable human review workspace |
| `review_final.xlsx` | Frozen execution contract |

## Data Flow & The Master State

At the heart of the L10n Audit Toolkit is **`audit_master.json`**. 

**Why does the Master exist?**
Historically, localization tools dumped dozens of scattered CSV and JSON files, forcing teams to manually stitch them together. If a file was missed, data was lost. 

The `audit_master.json` acts as the **single source of truth** for the entire pipeline. 
- **Idempotency:** Because all state is stored centrally, you can safely re-run stages without corrupting past results.
- **Traceability:** Every finding—whether from a regex rule or an AI suggestion—maintains its provenance and history.
- **Decoupling:** Output formats (like Excel or Markdown) are purely "dumb" projections. If an Excel file is deleted, it can be regenerated instantly from the master state without re-running the expensive AI review.

## Modules & Roles

- **Engine (`l10n_audit/core/`)**: Handles path discovery, framework detection, workspace isolation, and master state reconciliation.
- **Detectors (`l10n_audit/audits/`)**: Pure functions that take a string and return structured findings (e.g., missing placeholders, grammatical errors, semantic mismatch). They *never* write to your project directly.
- **Resolvers (`l10n_audit/fixes/`)**: Freeze approved rows into `review_final.xlsx` and safely write exact `.fix` files formatted exactly like the host framework (Laravel PHP or standard JSON).
- **Projections (`l10n_audit/reports/`)**: Turn the master dataset into user-friendly dashboards and queues downstream.
