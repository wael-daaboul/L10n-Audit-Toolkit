# Output Reports

## Output Philosophy

- **`audit_master.json`** = The absolute source of truth.
- All other outputs are merely projections of this master data.

```text
audit_master.json
   ↓
review_queue.xlsx
   ↓
apply
   ↓
reconcile
   ↓
final_audit_report
```

## Internal vs Public Outputs

- **`.cache/`** → Internal use only. Contains raw data fragments and temporary generation files. Do not build tooling around these.
- **`Results/`** → User-facing. Contains the final, stable, and intended artifacts for humans and CI/CD pipelines.

---

## Output Types

### Core Outputs (Always Generated)
- `Results/artifacts/audit_master.json`
- `Results/review/review_queue.xlsx` / `.json`
- `Results/final/final_audit_report.json` / `.md`

### Optional Outputs
- per-tool CSV/XLSX (disabled by default, enabled via specific CLI flags)

---

## Detailed Locations

### `.cache/raw_tools/`
Internal storage for raw outputs from individual audit modules. Avoid referencing directly.
- Placeholder audit JSON (CSV/XLSX disabled by default)
- Terminology audit JSON
- Locale QA reports
- ICU audit reports

### `Results/artifacts/`
Contains the authoritative application state.
- `audit_master.json`: The source of truth for the entire pipeline.

### `Results/review/`
Human-review artifacts intended for translators and localization managers.
- `review_queue.xlsx`: Excel sheet for human review.
- `review_queue.json`: Machine-readable equivalent.

### `Results/fixes/`
Safe-fix outputs and candidate logs.
- `fix_plan.json`
- `fix_plan.xlsx` (Optional)
- `safe_fixes_applied_report.json`

### `Results/final/`
Aggregated reporting outputs.
- `final_audit_report.md`: Dashboard-style single main report.
- `final_audit_report.json`

### `Results/final_locale/`
Final locale outputs after approved fixes are applied back to your project.

---

## Common Artifact Details

### Final Audit Dashboard (`Results/final/final_audit_report.md`)
Contains:
- Total issue counts and review-required metrics
- Prioritized findings

### Review Queue (`Results/review/review_queue.xlsx`)
Contains:
- Reviewable findings (AI suggestions, stylistic issues)
- Current locale value vs suggested fix
- Integrity metadata

### Safe Fix Plan (`Results/fixes/fix_plan.json`)
Contains:
- Deterministic candidate changes
- Classification and provenance

---

## Manual Execution (Advanced)
Normally handled automatically by the `fast` or `full` stages:
```bash
l10n-audit run --stage reports
```

For developers building raw modules, the module can be invoked explicitly:
```bash
python -m reports.report_aggregator --sources "localization,locale_qc,terminology"
```

## Output Simplification (v1.4+)

- Reduced redundant outputs
- Removed duplicate markdown files
- Focused on actionable artifacts

---

## Deprecation & Cleanup Notes

- We have removed redundant multilingual markdown outputs (`_en.md`, `_ar.md`).
- Some artifacts are currently retained *only* for CLI compatibility.
- Future versions may remove:
  - `per_tool` CSV/XLSX (CLI only)
  - `fix_plan.xlsx` (CLI only)
