# L10n Audit Toolkit

L10n Audit Toolkit is a Python-based localization QA toolkit for auditing translation files, validating runtime-sensitive strings, and producing safe localization review workflows for multilingual applications.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Status: Active](https://img.shields.io/badge/status-active-success)
![Release](https://img.shields.io/github/v/release/wael-daaboul/L10n-Audit-Toolkit)

📚 **Documentation:**
👉 <https://wael-daaboul.github.io/L10n-Audit-Toolkit/>

```bash
pipx install l10n-audit-toolkit
```

## Overview

L10n Audit Toolkit helps engineering and localization teams catch issues before translations ship to production. It combines code usage scanning, locale-file validation, placeholder validation, terminology audit, glossary enforcement, and translation QA reporting in a single repository-oriented workflow.

The project is designed for teams that need repeatable localization audits for i18n and l10n pipelines without rewriting their application structure. It supports JSON locale files and Laravel PHP translation files, generates machine-readable and spreadsheet reports, and keeps risky changes in a review queue instead of auto-applying them.

## Problem It Solves

Modern multilingual applications often fail in production because translation QA is fragmented across manual review, ad hoc scripts, and framework-specific checks. Common issues include:

- missing or unused translation keys
- placeholder mismatch detection failures
- glossary drift and terminology inconsistency
- ICU message mistakes
- unsafe formatting cleanup
- review workflows that are hard to trace or apply safely

L10n Audit Toolkit addresses those problems with a structured localization audit pipeline and explicit safe-fix boundaries.

## Key Features

- Localization audit workflow for repository-based translation QA
- Static translation usage scanning across supported frameworks
- Placeholder validation for common runtime interpolation styles
- Terminology audit and glossary enforcement
- English and Arabic locale quality checks
- ICU message validation
- Safe localization fixes with a review-required path for risky changes
- Review queue generation in XLSX for human approval
- Final locale export in the original supported format
- JSON, CSV, XLSX, and Markdown outputs for CI or manual review

## Supported Frameworks and Formats

Built-in project profiles currently cover:

- Flutter with GetX JSON localization
- Laravel JSON localization
- Laravel PHP localization
- React with i18next JSON
- Vue with `vue-i18n` JSON

Current locale format support:

- JSON locale files
- Laravel PHP translation files that use static parseable return arrays such as `return [...]` and `return array(...)`

## What The Toolkit Detects

The toolkit can report issues such as:

- missing translations
- unused keys
- placeholder mismatch detection problems
- renamed or reordered placeholders
- terminology violations
- glossary enforcement failures
- ICU syntax and branch mismatches
- English locale wording and grammar issues
- Arabic locale spacing, punctuation, and context-sensitive review findings
- Arabic semantic review suggestions for sentence-level meaning loss
- risky review items that require explicit human approval

## 🚀 Quick Start

The L10n Audit Toolkit now comes with a powerful CLI. To get started in your localization project:

1. **Initialize Workspace:**

   ```bash
   l10n-audit init
   ```

2. **Verify Setup:**

   ```bash
   l10n-audit doctor
   ```

3. **Run a Fast Audit:**

   ```bash
   l10n-audit run --stage fast
   ```

Primary outputs are written under `Results/`.

## 💻 CLI Commands

Here are the main commands you will use daily:

- `l10n-audit --help` - Shows help, usage instructions, and available arguments.
- `l10n-audit --version` - Displays the current installed version of the toolkit.
- `l10n-audit init` - Discovers your project and creates the `.l10n-audit/` workspace.
- `l10n-audit run --stage <STAGE>` - Runs specific or all audit modules (e.g., `fast`, `full`, `autofix`).
- `l10n-audit update` - Fetches the latest global rules and dictionaries to your local workspace.

### 🤖 AI-Powered Review

You can enhance your audits with AI (e.g., OpenAI, OpenRouter) to check context, tone, and grammar:

```bash
l10n-audit run --stage ai-review \
  --ai-enabled \
  --ai-api-base "https://openrouter.ai/api/v1" \
  --ai-model "openai/gpt-4o-mini"
```

> **Note:** For deep technical details and developer scripts, check the `docs/` folder.

If you are using the repository checkout directly rather than an installed launcher, you can still run:

```bash
./bin/run_all_audits.sh --stage fast
```

## Installation

Use the bootstrap script for the fastest setup:

```bash
./bootstrap.sh
```

Manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
python -m pip install -r requirements-dev.txt
```

Detailed environment setup is documented in [INSTALL.md](INSTALL.md) and [docs/quickstart.md](docs/quickstart.md).

The repository ships with a neutral example glossary at `docs/terminology/glossary.json`. Replace it or point `glossary_file` to your own JSON glossary.

## Running Audits

Run the full localization audit pipeline:

```bash
l10n-audit run --stage full
```

Useful stage-specific commands:

```bash
l10n-audit run --stage ai-review --ai-enabled
l10n-audit run --stage ai-review --ai-enabled --ai-model gpt-4o-mini --ai-api-base https://api.openai.com/v1
l10n-audit doctor
l10n-audit update --check
```

To refresh local workspace templates from GitHub or a direct archive URL:

```bash
l10n-audit init --from-github --channel stable --repo https://github.com/your-org/l10n-audit-toolkit
l10n-audit update --from-github --channel main --repo https://github.com/your-org/l10n-audit-toolkit
```

You can also pass a direct `.zip` archive URL or `file://...zip` path during testing.

You can also run the basic localization usage audit directly:

```bash
./bin/l10n_audit.sh
```

## Safe Fixes and Review Workflow

The toolkit separates deterministic changes from human-reviewed changes.

1. Run audits and generate reports.
2. Review `Results/final/final_audit_report.md`.
3. Open `Results/review/review_queue.xlsx`.
4. Fill `approved_new` for reviewed rows and set `status` to `approved`.
5. Apply approved fixes with:

```bash
python -m fixes.apply_review_fixes
```

6. Use the final locale output from `Results/final_locale/`.

Safe auto-fix planning is available with:

```bash
./bin/run_all_audits.sh --stage autofix
```

The review and fix workflow is documented in [HOW_TO_USE.md](HOW_TO_USE.md) and [docs/review_workflow.md](docs/review_workflow.md).

## Example CLI Usage

```bash
./bin/run_all_audits.sh --stage full
python -m audits.placeholder_audit
python -m audits.terminology_audit
python -m fixes.apply_safe_fixes
python -m fixes.apply_review_fixes
python -m pytest
```

## Example Outputs

Common outputs include:

- `Results/per_tool/`: raw per-audit findings
- `Results/normalized/`: normalized machine-readable findings
- `Results/review/review_queue.xlsx`: review queue for human approval
- `Results/fixes/fix_plan.json`: safe fix plan
- `Results/fixes/safe_fixes_applied_report.json`: auto-fix summary
- `Results/final/final_audit_report.md`: aggregated dashboard
- `Results/final_locale/ar.final.json`: final reviewed locale

See [docs/output_reports.md](docs/output_reports.md) for report details.

## Repository Structure

- `audits/`: audit modules for localization, placeholder, terminology, ICU, and locale QA checks
- `core/`: shared runtime, loaders, exporters, scanners, and validation helpers
- `fixes/`: safe-fix and reviewed-fix application logic
- `reports/`: report aggregation and final dashboard generation
- `schemas/`: JSON schemas for config and generated artifacts
- `config/`: toolkit configuration and project profiles
- `bin/`: shell entry points for common workflows
- `examples/`: framework-oriented sample layouts and usage notes
- `docs/`: reference documentation for workflows and outputs
- `tests/`: regression coverage for audits, exports, reports, and fix safety

Detailed directory roles are documented in [docs/overview.md](docs/overview.md).

## Documentation

- [INSTALL.md](INSTALL.md): environment and dependency setup
- [HOW_TO_USE.md](HOW_TO_USE.md): workflow-oriented usage guide
- [docs/quickstart.md](docs/quickstart.md): shortest path to first successful run
- [docs/audit_modules.md](docs/audit_modules.md): audit module reference
- [docs/review_workflow.md](docs/review_workflow.md): fix plan and review queue behavior
- [docs/ai_usage.md](docs/ai_usage.md): AI-assisted translation review and CLI options
- [docs/output_reports.md](docs/output_reports.md): generated outputs and report formats
- [docs/configuration.md](docs/configuration.md): detailed configuration schema and profiles
- [docs/ci_cd_integration.md](docs/ci_cd_integration.md): GitHub Actions and GitLab CI setups
- [docs/terminology_guide.md](docs/terminology_guide.md): formatting your custom glossary.json
- [examples/README.md](examples/README.md): supported example layouts

## Contributing

Contributions that improve localization audit quality, translation validation, framework coverage, or documentation are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

Please report vulnerabilities privately. See [SECURITY.md](SECURITY.md).

## License

This repository is released under the MIT License. See [LICENSE](LICENSE).
