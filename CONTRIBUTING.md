# Contributing to L10n Audit Toolkit

Thank you for contributing. This repository aims to stay reviewable, testable, and conservative around localization data integrity.

## Reporting Issues

Please open a GitHub issue when you find a bug, a documentation problem, or a feature gap.

When possible, include:

- A short, specific title
- The framework or project profile involved
- The locale format involved
- Steps to reproduce the problem
- Expected behavior
- Actual behavior
- Relevant configuration snippets from `config/config.json`
- Sample locale files or source snippets if they are needed to reproduce the issue

If the report is about incorrect audit output, include the generated files from `Results/` that demonstrate the problem.

## Proposing Changes

1. Fork the repository.
2. Create a focused branch for your change.
3. Make the smallest reasonable change that solves the problem.
4. Add or update tests when behavior changes.
5. Update documentation when commands, configuration, or outputs change.
6. Open a pull request with a clear description of the change and its motivation.

Good contribution areas include:

- localization audit accuracy
- placeholder validation improvements
- terminology and glossary workflows
- documentation and onboarding
- framework-profile examples

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-optional.txt
python -m pip install -r requirements-dev.txt
```

Or use:

```bash
./bootstrap.sh --with-tests
```

## Before Opening a Pull Request

Run the relevant validation commands for your change:

```bash
python -m pytest tests
python -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json
```

If your change affects audit behavior, run at least one representative audit stage locally:

```bash
./bin/run_all_audits.sh --stage fast
```

For broader validation:

```bash
./bin/run_all_audits.sh --stage full
```

After generating audit outputs, you can also run:

```bash
python -m core.schema_validation --preset core
```

## Pull Request Guidelines

- Keep pull requests focused on a single problem or improvement.
- Explain any behavior changes clearly.
- Reference the related issue when one exists.
- Include tests for bug fixes and feature work when practical.
- Avoid unrelated refactors in the same pull request.
- Describe how you validated the change locally.
- Update screenshots, example commands, or docs when workflow outputs change.

## Scope Notes

The project currently supports JSON locale files and Laravel PHP translation files with safe static parseable return structures such as `return [...]` and `return array(...)`. Contributions that expand format or framework support should preserve existing behavior for the supported profiles and include tests for the new path.
