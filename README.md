# L10n Audit Toolkit

Automated localization auditing, validation, and repair — built for real-world production pipelines.

[![Version](https://img.shields.io/badge/version-1.4.0-blue.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Architecture](https://img.shields.io/badge/Architecture-Universal-green.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)

---

## 🚀 What’s New in v1.4

- Cleaner outputs (less noise)
- Single source of truth (audit_master.json)
- Safer apply workflow (no data drift)
- Improved performance and clarity

---

## 💡 Why This Tool Is Different

- No split-brain after apply
- Deterministic reconciliation
- Designed for production workflows
- Master-first architecture

---

## 🛑 What Problem It Solves

Localization often breaks in subtle ways that automated tests miss and human reviewers overlook:
- Inconsistent terminology across hundreds of keys.
- Broken placeholders (e.g., UI variables lost in translation).
- Mixed-script errors (e.g., hidden English characters in Arabic text).
- "Good enough" translations that miss the semantic context.

**L10n Audit Toolkit** provides a deterministic, repeatable, and automated pipeline to catch these issues before they reach production. It acts as a safety net between translators language files and your codebase.

---

## ✨ Key Features

- **🔍 Multi-stage audit pipeline:** Fast rules-based checks, full ICU validation, and optional AI-driven semantic review.
- **🧠 AI-assisted review (optional):** Intelligently analyzes context to suggest culturally and semantically accurate translations.
- **🔁 Reconciliation-safe apply system:** Safely merges approved human and machine fixes back into your original files.
- **📦 Centralized audit master:** A single source of truth (`audit_master.json`) for the entire pipeline state.
- **⚙️ CLI-first workflow:** Designed for CI/CD integration with structured, deterministic outputs.

---

## 🚀 Quickstart

```bash
# 1. Initialize your workspace (detects framework, sets up .l10n-audit/)
l10n-audit init

# 2. Run the audit pipeline against your locale files
l10n-audit run

# 3. Apply reviewed fixes back to your codebase
l10n-audit apply
```

This generates:

- `Results/final/final_audit_report.json`
- `Results/review/review_queue.xlsx`
- `Results/artifacts/audit_master.json`

---

## 📊 Output Overview

The toolkit generates a structured set of outputs to guide both humans and machines:

- **`Results/artifacts/audit_master.json`** → The core application state and single source of truth.
- **`Results/review/review_queue.xlsx`** → The human-friendly Excel sheet for translators to approve or reject suggestions.
- **`Results/final/final_audit_report.md`** → The dashboard-style Markdown summary of your localization health.

> **⚠️ Note:** 
> - Per-tool CSV/XLSX outputs are optional and disabled by default to reduce noise.
> - The `.cache/` directory contains internal, raw processing data and should be ignored by version control.

---

## 🏗️ Architecture (High-Level)

The toolkit operates on a unidirectional, safe pipeline:

1. **Audit:** Reads project locales and runs heuristics/AI to detect issues.
2. **Aggregate:** Merges all findings into `audit_master.json`.
3. **Review:** Projects the master state into human-readable views (e.g., `review_queue.xlsx`).
4. **Apply:** Reads human decisions and applies safe fixes to temporary `.fix` files.
5. **Reconcile:** Merges the application results back into the master state for a complete audit trail.

---

## 👥 Who Should Use This

- **Localization Teams:** Ensure comprehensive terminology consistency without manual grepping.
- **Developers:** Catch broken placeholders or formatting variables before deployment.
- **QA Teams:** Automate multi-language validation within CI/CD pipelines to guarantee UI integrity.

---

📚 **Documentation:**
👉 <https://wael-daaboul.github.io/L10n-Audit-Toolkit/>