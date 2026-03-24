# 🌍 L10n Audit Toolkit (v1.3.0)

[![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Architecture](https://img.shields.io/badge/Architecture-Universal-green.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Tests](https://img.shields.io/badge/Tests-142%20Passed-brightgreen.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
![Release](https://img.shields.io/github/v/release/wael-daaboul/L10n-Audit-Toolkit)


📚 **Documentation:**
👉 <https://wael-daaboul.github.io/L10n-Audit-Toolkit/>

```bash
pipx install l10n-audit-toolkit
```


The **L10n Audit Toolkit** is a professional-grade, project-agnostic localization QA and translation audit engine. Designed for modern engineering teams, it provides automated linguistic validation, semantic risk assessment, and smart auto-fixing for complex, multi-framework applications.

---

## 🏗️ Version 1.3.0: Persistent Staging & Terminology Enforcement

Starting with **v1.3.0**, the toolkit introduces **Persistent Staging** for verified translations and **Strict Glossary Enforcement** with AI self-correction logic.

> [!IMPORTANT]
> This version introduces the `.l10n-audit/staged/` directory. Translations verified in previous runs are now persisted and automatically applied in subsequent audits (Idempotency), ensuring that manual approvals are never lost.

---

## 🚀 Key Features in v1.3.0

### 🛡️ Persistent Staged Storage
Verified translations are moved to a protected `.l10n-audit/staged/` directory.
- **Auto-Migration**: Once a translation is marked as "verified", it is automatically migrated to the staged area.
- **Idempotency**: The `autofix` stage prioritizes staged translations over new suggestions, preventing "correction loops".
- **Safety**: The `staged/` directory is never cleared by standard cleanup routines.

### 📚 Strict Glossary Enforcement & AI Retries
The AI review engine now strictly follows your `glossary.json`.
- **Glossary Validation**: Every AI suggestion is checked against the glossary before being accepted.
- **Smart Retries**: If an AI suggestion violates glossary rules, the engine automatically retries (up to 3 times).
- **Negative Prompts**: Retries include explicit feedback to the AI about the specific violation, forcing better compliance.

### 🛠️ Integrated Auto-Fixer
The `autofix` stage has been refactored to be more robust:
- **Direct Scan Pass**: Automatically fixes common whitespace and punctuation issues without AI calls.
- **Safe AI Integration**: Only applies AI suggestions that pass strict validation (placeholders, HTML, glossary).
- **Excluded Paths**: Respects `excluded_paths` in `config.json` to avoid touching sensitive files.

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
