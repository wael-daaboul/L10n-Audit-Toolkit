# Project Documentation

## Project Overview

L10n Audit Toolkit is a Python-based localization quality assurance toolkit for auditing, reviewing, and safely applying fixes to application locale files.

The application solves the operational problem of localization drift: missing keys, inconsistent terminology, broken placeholders, ICU formatting errors, Arabic quality issues, grammar issues, and review-only semantic concerns that are often missed by ordinary test suites.

The primary target audience is:

- Localization engineers and localization project managers.
- Software developers maintaining multilingual products.
- QA teams validating release readiness for localized applications.
- CI/CD owners who need repeatable translation-quality checks.

The project goals are:

- Provide deterministic, repeatable localization audits.
- Keep source locale identity and apply safety enforceable.
- Separate machine discovery, human review, frozen apply contracts, and final reconciliation.
- Support multiple project profiles and locale formats without coupling audit logic to one framework.
- Preserve clear audit trails through generated artifacts and documentation.

## Technology Stack

- **Language:** Python 3.10+.
- **Packaging:** `setuptools` via `pyproject.toml`.
- **CLI:** `argparse` exposed through the `l10n-audit` console script.
- **Runtime libraries:** `python-dotenv`, `litellm`, `openpyxl`, `language-tool-python`.
- **Optional libraries:** `pandas`, `rich`, `rapidfuzz`, `python-Levenshtein`, `textblob`, `nltk`, `regex`, `jsonschema`, `PyYAML`.
- **Testing:** `pytest`; development dependencies also include `ruff` and `mypy`.
- **HTTP API:** optional FastAPI reference server in `http_api/server.py`.
- **External services:** optional OpenAI-compatible AI providers through LiteLLM; optional local LanguageTool through Java.
- **Databases:** no server database. Persistent state is file-based JSON/XLSX under `Results/` and `.l10n-audit/`.

## Project Structure

- `l10n_audit/`: main Python package.
- `l10n_audit/core/`: orchestration, CLI, runtime loading, workspace isolation, profile detection, source identity, manifest application, AI provider wiring, schema validation, and result management.
- `l10n_audit/audits/`: audit modules for consistency, placeholders, terminology, ICU, grammar, Arabic QC, Arabic semantic review, AI review, and CAMeL validation.
- `l10n_audit/fixes/`: safe-fix, review-fix, glossary-fix, and fix-merger logic.
- `l10n_audit/reports/`: report aggregation and review queue projection.
- `l10n_audit/ai/`: AI prompts, provider integration, and verification helpers.
- `l10n_audit/contracts/`: frozen contract definitions such as decision quality contracts.
- `l10n_audit/core/locale_loaders/`: locale readers for JSON and Laravel PHP formats.
- `l10n_audit/core/locale_exporters/`: locale writers for JSON and Laravel PHP formats.
- `schemas/` and `l10n_audit/schemas/`: configuration and report schemas.
- `config/`: example and local configuration templates.
- `docs/`: project documentation, user guides, architecture notes, terminology guidance, and official requirement documents.
- `AGENTS.md`: mandatory operating guide for developers and AI agents.
- `docs/architecture/`: detailed architecture baseline, pipeline analysis, CAMeL analysis, and refactor planning documents.
- `docs/user_guides/`: install and usage guides in English and Arabic.
- `docs/terminology/`: glossary data used by terminology audits.
- `examples/`: sample projects for Flutter/GetX, Laravel JSON, Laravel PHP, React i18next, and Vue i18n.
- `http_api/`: optional FastAPI wrapper around the public Python API.
- `bin/`: legacy shell launchers kept for compatibility.
- `tests/`: regression, unit, CLI, artifact governance, apply-contract, schema, and quality-layer tests.
- `Results/`: generated audit outputs; not a source directory.
- `.l10n-audit/`: local isolated workspace and generated runtime artifacts.

## Component Relationships

- The CLI in `l10n_audit/core/cli.py` calls the public API in `l10n_audit/api.py`.
- The public API validates inputs and delegates audit execution to `l10n_audit/core/engine.py`.
- The engine builds an isolated runtime using workspace and configuration helpers.
- Audit modules emit structured findings without directly mutating project files.
- Report aggregation normalizes findings into master artifacts and review workbooks.
- `prepare-apply` freezes approved review rows into `review_final.xlsx`.
- `apply` consumes only `review_final.xlsx`, validates source identity, and writes safe `.fix` outputs.
- Reconciliation updates the master state to preserve audit traceability.
- The optional HTTP API wraps the same public Python functions used by the CLI.

## Development Workflow

### Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
l10n-audit init
l10n-audit run --stage fast
```

### Primary Review/Apply Workflow

```text
run -> review_queue.xlsx -> prepare-apply -> review_final.xlsx -> apply
```

`review_queue.xlsx` is the editable human review workspace. `review_final.xlsx` is the frozen execution contract and must not be edited manually.

### Adaptive Configuration Workflow

```text
generate-adaptation-report -> generate-manifest -> review-manifest -> apply-manifest
```

This workflow is explicit, review-gated, and separate from normal audit execution.

### Build for Distribution

```bash
python -m build
```

### Run Tests

```bash
pytest
```

### Environment Management

- Configuration is loaded from `config.json`, `.l10n-audit/`, and supported environment variables.
- Optional AI review uses provider credentials from CLI arguments or environment variables.
- LanguageTool requires Java and a local or discoverable LanguageTool runtime.
- Generated results should remain separate from source-controlled project files unless intentionally archived.
- GitHub uploads are governed by `.gitignore`, which excludes local secrets, private configs, generated audit artifacts, caches, virtual environments, and bundled vendor tools while keeping documentation and examples eligible for version control.

## Documentation Index

### Official Requirement and Architecture Documents

- `AGENTS.md`: mandatory operating guide and startup checklist for all future development work.
- `docs/PROJECT_DOCUMENTATION.md`: main project reference and documentation index.
- `docs/BRS.md`: business requirements specification.
- `docs/FRS.md`: functional requirements specification.
- `docs/NFR.md`: non-functional requirements.
- `docs/SRS.md`: consolidated software requirements specification.
- `docs/USE_CASES.md`: use case specifications.
- `docs/USE_CASE_DIAGRAM.md`: use case relationships and Mermaid UML diagram.
- `docs/ARCHITECTURE.md`: system architecture.
- `docs/ADR.md`: architecture decision records.
- `docs/DATABASE.md`: file-based data and artifact documentation.
- `docs/API.md`: HTTP, CLI, and Python API documentation.
- `docs/UI_UX.md`: CLI/report/review-workbook UX documentation.
- `docs/CHANGELOG.md`: documentation and project change log.

### Existing Supporting Documents

- `README.md`: public overview and quickstart.
- `CHANGELOG.md`: release history.
- `CONTRIBUTING.md`: contribution workflow.
- `SECURITY.md`: vulnerability reporting and scope.
- `ROADMAP.md`: roadmap.
- `docs/overview.md`: system overview.
- `docs/quickstart.md`: quick start guide.
- `docs/audit_modules.md`: audit module reference.
- `docs/configuration.md`: configuration reference.
- `docs/output_reports.md`: output artifact reference.
- `docs/review_workflow.md`: human review and apply workflow.
- `docs/ai_usage.md`: AI-assisted review guide.
- `docs/ci_cd_integration.md`: CI/CD usage patterns.
- `docs/terminology_guide.md`: glossary format and terminology rules.
- `docs/user_guides/INSTALL.md`: installation guide.
- `docs/user_guides/HOW_TO_USE.md`: full usage guide.
- `docs/user_guides/USAGE_AR.md`: Arabic usage guide.
- `docs/architecture/*.md`: detailed architecture analysis and planning.
