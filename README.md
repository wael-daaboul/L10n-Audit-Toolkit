# 🌍 L10n Audit Toolkit (v1.3.1)

[![Version](https://img.shields.io/badge/version-1.3.1-blue.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Architecture](https://img.shields.io/badge/Architecture-Universal-green.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Tests](https://img.shields.io/badge/Tests-154%20Passed-brightgreen.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
![Release](https://img.shields.io/github/v/release/wael-daaboul/L10n-Audit-Toolkit)


📚 **Documentation:**
👉 <https://wael-daaboul.github.io/L10n-Audit-Toolkit/>

```bash
pipx install l10n-audit-toolkit
```


The **L10n Audit Toolkit** is a professional-grade, project-agnostic localization QA and translation audit engine. Designed for modern engineering teams, it provides automated linguistic validation, semantic risk assessment, and smart auto-fixing for complex, multi-framework applications.

---

## 🏗️ Version 1.3.1: Workspace Isolation & AI Preprocessing

Starting with **v1.3.1**, the toolkit introduces **Workspace Isolation** to protect project files and **English Preprocessing** to enhance AI translation quality.

> [!IMPORTANT]
> The audit engine now operates within an isolated `.l10n-audit/workspace/` environment. Project files are copied for analysis, and findings are exported as separate `.fix` files, ensuring that your original codebase remains untouched until you explicitly apply the fixes.

---

## 🚀 Key Features in v1.3.1

### 🛡️ Full Workspace Isolation
All audits now run on temporary copies of your locale files.
- **Safety**: Original project files are never modified during the audit.
- **Support**: Native support for file-based (JSON) and folder-based (Laravel PHP) structures.
- **Cleanup**: Automatic workspace management prevents data pollution between runs.

### 🧹 English Preprocessing
Automated cleaning of English source text before it reaches the AI.
- **Noise Filtering**: Removes common typos and technical artifacts.
- **Contraction Handling**: Fixes common issues like `dont` -> `don't` or `cant` -> `can't`.
- **Quality**: Better input results in significantly more accurate AI-suggested translations.

### 🔄 Unified Fix Merger
A streamlined engine to consolidate all corrections.
- **Merging**: Combines `auto_safe` corrections with human-approved fixes from `review_queue.xlsx`.
- **Exporting**: Generates `.fix` files (e.g., `en.fix.json` or `lang.fix/`) maintaining the original structure.
- **Human-in-the-Loop**: Seamlessly integrates reviewed items into the final patch.

### 🛡️ Persistent Staged Storage (v1.3.0+)
Verified translations are moved to a protected `.l10n-audit/staged/` directory for idempotency and safety.

---

## 🚀 Quick Start & Configuration

The toolkit uses a **Self-Documenting Configuration** system with vertical, bilingual (Arabic/English) annotations to eliminate any ambiguity.

### 1. Initialize Your Workspace
Run the following command in your project root to generate the necessary directory structure:
```bash
l10n-audit init
```

### 2. Configure Your Audit
Copy the provided template and customize it to your project's needs:
```bash
cp config.json.example config.json
```

### 3. Namespace Overview
Your `config.json` is organized into logical namespaces:

| Namespace | Responsibility | Primary Settings |
| :--- | :--- | :--- |
| **`project_detection`** | Framework discovery | `auto_detect`, `force_profile` |
| **`audit_rules`** | Linguistic precision | `role_identifiers`, `latin_whitelist`, `apply_safe_fixes` |
| **`ai_review`** | Semantic intelligence | `enabled`, `provider`, `model`, `api_key_env` |
| **`output`** | Results management | `results_dir`, `retention_mode`, `excluded_paths` |

---

## ⌨️ CLI Command Reference

| Command | Description |
| :--- | :--- |
| `l10n-audit --version` | Verify installation (should show **1.3.0**) |
| `l10n-audit run --stage fast` | Perform terminology and QC checks only |
| `l10n-audit run --stage full` | Run the complete audit suite (Grammar, AI, Terminology, QC) |
| `l10n-audit run --stage autofix` | Audit and automatically apply safe/verified fixes |
| `l10n-audit doctor` | Diagnose workspace and framework discovery issues |

---

## 📝 Technical Notes for Power Users

- **Brand Protection**: Use the `latin_whitelist` in `audit_rules` to prevent the engine from flagging your brand name or technical terms as 'mixed-script' errors.
- **Context Preservation**: Defining `role_identifiers` (e.g., `['admin', 'captain']`) ensures the AI and heuristic engines understand your app's specific persona contexts.
- **Performance**: Batch sizes can be adjusted via `ai_review.batch_size` (default: 20) to balance between execution speed and API rate limits.
- **Error Logging**: In case of critical glossary violations or AI failures, the tool logs detailed information to `logs/audit_errors.log`. Check this file if an audit fails with a `GlossaryViolationError`.

---

## 🤝 Contributing & Support
For issues, architectural questions, or feature requests, please refer to the internal documentation or contact the **Advanced Agentic Coding** team.