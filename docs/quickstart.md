# Quick Start

## 1. Initialize
Sets up the `.l10n-audit/` workspace and creates a default `config.json` tailored to your detected framework.
```bash
l10n-audit init
```

## 2. Run Audit
Analyzes your locale files without modifying them. Results are safely aggregated in the workspace.
```bash
l10n-audit run --stage fast
```

### Expected Outputs
After running `l10n-audit run`, you will immediately see:
- **final report:** `Results/final/final_audit_report.md`
- **review queue:** `Results/review/review_queue.xlsx`
- **master state:** `Results/artifacts/audit_master.json`

## 3. Review Results
Open the generated spreadsheet to approve or reject suggestions, or view the overall dashboard.
- **Dashboard:** `Results/final/final_audit_report.md`
- **Review Sheet:** `Results/review/review_queue.xlsx`

## 4. Freeze Approved Rows
Generate the frozen execution workbook before apply:
```bash
l10n-audit prepare-apply
```

This command transforms the editable review workspace into a deterministic, execution-safe contract.

This produces:
- **frozen execution workbook:** `Results/review/review_final.xlsx`

| File | Role |
| :--- | :--- |
| `review_queue.xlsx` | Editable human review workspace |
| `review_final.xlsx` | Frozen execution contract |

Do not edit `review_final.xlsx` manually. If you update `review_queue.xlsx` after freezing, run `prepare-apply` again.

## 5. Apply Fixes
Safely merges approved rows from `review_final.xlsx` and automated safe fixes back into your project files.
```bash
l10n-audit apply
```

`apply` reads only `review_final.xlsx`. It never applies directly from `review_queue.xlsx`.

## 6. Adaptive Config Workflow
Use the adaptive workflow only when you want explicit, human-reviewed config changes:

```bash
l10n-audit generate-adaptation-report --learning-profile <PATH> --mode prepare_bounded_actions
l10n-audit generate-manifest --input-report <ADAPTATION_REPORT_JSON>
l10n-audit review-manifest --manifest <MANIFEST_JSON> --approvals <APPROVALS_JSON>
l10n-audit apply-manifest --manifest <MANIFEST_JSON> --reviewed-manifest <REVIEWED_MANIFEST_JSON>
```

This workflow is separate from `run -> prepare-apply -> apply`. It does not run automatically during `run`.

---
**Where to go next:**
- [Output Reports Details](output_reports.md)
- [Review Workflow](review_workflow.md)
