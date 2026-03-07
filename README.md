# L10n Audit Toolkit

Cross-framework localization audit and translation QA tooling for Python-based repository workflows.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Status: Active](https://img.shields.io/badge/status-active-success)

L10n Audit Toolkit is a cross-framework localization auditing toolkit written in Python. It helps teams review localization, i18n, translation QA, and localization audit results by analyzing locale files and translation usage in source code before release.

## Features

- Automatic project type detection for supported frameworks
- Localization key usage scanning in application source code
- Detection of unused localization keys
- Detection of missing translations
- Placeholder mismatch detection
- Terminology validation against a glossary
- English grammar checking with local LanguageTool support and built-in fallback rules
- ICU message validation
- Safe autofix plan generation
- Export of fixed translations back to the original source format
- Structured report generation in JSON, CSV, XLSX, and Markdown

## Use Cases

- Audit a project before release to catch missing or unused translation keys
- Review placeholder consistency between source and target locales
- Validate terminology against a project glossary
- Run grammar and ICU checks as part of localization QA
- Generate structured reports and safe fix candidates for manual review

## Supported Frameworks

The toolkit currently includes built-in project profiles for:

- Flutter with GetX JSON localization
- Laravel PHP localization in `resources/lang/*.php`
- Laravel JSON localization
- React with i18next JSON
- Vue with `vue-i18n` JSON

Current locale format support:

- JSON locale files
- Laravel PHP translation files with safe static parseable return structures such as `return [...]` and `return array(...)`

## Quick Start

1. Review and update `config/config.json` for your target project.
2. Create and activate a virtual environment.
3. Install dependencies.
4. Run a fast or full audit stage.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
./bin/run_all_audits.sh --stage fast
```

Useful follow-up commands:

```bash
python -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json
python -m pytest tests
./bin/run_all_audits.sh --stage autofix
```

## Architecture

The repository is organized as a reusable audit pipeline:

- `audits/`: audit modules for localization usage, locale QC, grammar, ICU, placeholders, and terminology
- `core/`: shared runtime, project profile detection, scanners, loaders, exporters, and schema helpers
- `bin/`: shell entry points for common workflows
- `fixes/`: safe fix plan generation and candidate export logic
- `reports/`: final report aggregation
- `schemas/`: JSON schemas for configuration and output contracts
- `tests/`: pytest regression suite
- `examples/`: sample layouts for supported project profiles
- `vendor/LanguageTool-6.6/`: bundled local grammar tooling

At runtime, the toolkit:

1. Loads configuration from `config/config.json`.
2. Detects or applies the selected project profile.
3. Resolves locale sources, source code directories, glossary paths, and output folders.
4. Runs one or more audits against locale data and code usage.
5. Writes per-tool reports under `Results/per_tool/`.
6. Aggregates normalized findings into final reports under `Results/final/`.
7. Optionally generates a safe fix plan and export candidates under `Results/fixes/` and `Results/exports/`.

## Installation

### Requirements

- Python 3.10+
- Java for deeper grammar checking with the bundled LanguageTool distribution

### Setup From Source

```bash
git clone https://github.com/<your-account>/l10n-audit-toolkit.git
cd l10n-audit-toolkit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
```

To install development dependencies as well:

```bash
python -m pip install -r requirements-dev.txt
```

You can also bootstrap the environment with the repository script:

```bash
./bootstrap.sh
./bootstrap.sh --with-tests --validate-schemas
```

## Example Commands

Run only terminology validation:

```bash
./bin/run_all_audits.sh --stage terminology
```

Run only ICU validation:

```bash
./bin/run_all_audits.sh --stage icu
```

Rebuild final aggregated reports from existing per-tool outputs:

```bash
./bin/run_all_audits.sh --stage reports
```

Run schema validation directly:

```bash
python -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
```

Validate the full generated report contracts after running audits:

```bash
python -m core.schema_validation --preset core
```

Run the safe fix generator directly:

```bash
python -m fixes.apply_safe_fixes
```

## Project Structure

```text
.
├── audits/
├── bin/
├── config/
├── core/
├── docs/
├── examples/
├── fixes/
├── reports/
├── schemas/
├── tests/
├── vendor/
├── bootstrap.sh
├── HOW_TO_USE.md
├── INSTALL.md
└── README.md
```

## Output Reports

Generated artifacts are written under `Results/`:

- `Results/per_tool/`: raw audit outputs per module
- `Results/normalized/`: normalized machine-readable issue collections
- `Results/final/`: aggregated final reports
- `Results/fixes/`: fix plan outputs and candidate fixed locales
- `Results/exports/`: exported locale files in the original source format

Typical outputs include:

- JSON reports for machine-readable issue processing
- CSV and XLSX reports for audit review workflows
- Markdown reports for human-readable summaries
- Candidate fixed locale files and export-ready outputs

## Notes

- Automatic profile detection supports the built-in profiles only.
- Laravel PHP support is limited to safe static parseable translation return structures such as `return [...]` and `return array(...)`.
- Grammar audit can fall back to deterministic local rules when Java or LanguageTool is unavailable.
- Example profile layouts are available under `examples/`.

## Keywords

`localization`, `i18n`, `l10n`, `translation`, `translation-qa`, `localization-audit`, `flutter`, `laravel`, `react`, `vue`, `developer-tools`

## License

This project is licensed under the MIT License. See `LICENSE`.
# L10n-Audit-Toolkit
