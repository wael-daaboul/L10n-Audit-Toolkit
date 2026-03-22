# 🌍 L10n Audit Toolkit (v1.2.4)

[![Version](https://img.shields.io/badge/version-1.2.4-blue.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Architecture](https://img.shields.io/badge/Architecture-Universal-green.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
[![Tests](https://img.shields.io/badge/Tests-139%20Passed-brightgreen.svg)](https://github.com/wael-daaboul/L10n-Audit-Toolkit)
![Release](https://img.shields.io/github/v/release/wael-daaboul/L10n-Audit-Toolkit)


📚 **Documentation:**
👉 <https://wael-daaboul.github.io/L10n-Audit-Toolkit/>

```bash
pipx install l10n-audit-toolkit
```


The **L10n Audit Toolkit** is a professional-grade, project-agnostic localization QA and translation audit engine. Designed for modern engineering teams, it provides automated linguistic validation, semantic risk assessment, and smart auto-fixing for complex, multi-framework applications.

---

## 🏗️ Version 1.2.4: Universal Architecture

Starting with **v1.2.4**, the toolkit has transitioned to a **Universal, Data-Driven Architecture**. The core engine is now completely decoupled from specific project domains or frameworks.

> [!IMPORTANT]
> All audit logic, terminology rules, and entity protections are now dynamically driven by your local configuration. This means the tool works flawlessly for medical apps, banking platforms, ridesharing services, or games without any code changes.

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
Your `config.json` is organized into four logical namespaces:

| Namespace | Responsibility | Primary Settings |
| :--- | :--- | :--- |
| **`project_detection`** | Framework discovery | `auto_detect`, `force_profile` |
| **`audit_rules`** | Linguistic precision | `role_identifiers`, `latin_whitelist`, `apply_safe_fixes` |
| **`ai_review`** | Semantic intelligence | `enabled`, `provider`, `model`, `api_key_env` |
| **`output`** | Results management | `results_dir`, `retention_mode` |

---

## 💎 Core Features

### 🧠 Smart AI Semantic Review
V1.2.4 integrates **LiteLLM** to provide deep semantic validation of identified issues. This eliminates false positives by understanding the intent and context of your translations.
- **Provider Agnostic**: Supports OpenAI, DeepSeek, Anthropic, and local models.
- **Cost Optimization**: Use `low-cost 'mini' models` (e.g., `gpt-4o-mini`, `deepseek-chat`) and tune the `short_label_threshold` to skip trivial labels like "OK" or "Save".
- **Secure Integration**: Never hardcode keys; use `api_key_env` to point to your system's environment variables.

### 🛠️ The Smart Auto-Fixer (`--apply-safe-fixes`)
Standardize your terminology automatically. If enabled, the tool will read `glossary.json` and replace `forbidden_terms` with their approved equivalents directly in your locale files.
- **Whole-Word Matching**: Prevents accidental substring replacements.
- **RTL/LTR Aware**: Maintains script integrity during replacement.

### 📁 Results Archiving & Retention
Maintain full audit traceability across your project's history.
- **`overwrite`**: Default mode. Replaces the last audit's `Results` directory.
- **`archive`**: Moves previous results to a timestamped `_archives/` folder before starting a new run. Perfect for CI/CD audit trails.

---

## ⌨️ CLI Command Reference

Execute audits with precision using the standardized CLI interface.

| Command | Description |
| :--- | :--- |
| `l10n-audit --version` | Verify installation (should show **1.2.4**) |
| `l10n-audit run --stage fast` | Perform terminology and QC checks only |
| `l10n-audit run --stage full` | Run the complete audit suite (Grammar, AI, Terminology, QC) |
| `l10n-audit run --apply-safe-fixes` | Audit and automatically apply terminology corrections |
| `l10n-audit doctor` | Diagnose workspace and framework discovery issues |

---

## 📝 Technical Notes for Power Users

- **Brand Protection**: Use the `latin_whitelist` in `audit_rules` to prevent the engine from flagging your brand name or technical terms (e.g., "DeepSeek", "API") as 'mixed-script' errors in Arabic text.
- **Context Preservation**: Defining `role_identifiers` (e.g., `['admin', 'captain']`) ensures the AI and heuristic engines understand your app's specific persona contexts.
- **Performance**: Batch sizes can be adjusted via `ai_review.batch_size` (default: 20) to balance between execution speed and API rate limits.

---

## 🤝 Contributing & Support
For issues, architectural questions, or feature requests, please refer to the internal documentation or contact the **Advanced Agentic Coding** team.

---
*Generated by Antigravity AI for L10n-Audit v1.2.4*
