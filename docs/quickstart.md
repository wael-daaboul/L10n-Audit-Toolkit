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

## 4. Apply Fixes
Safely merges your approved human decisions and automated safe fixes back into your project files.
```bash
l10n-audit apply
```

---
**Where to go next:**
- [Output Reports Details](output_reports.md)
- [Review Workflow](review_workflow.md)
