# Quick Start

## Goal

This guide gets a developer from clone to first audit results with the fewest steps.

## 1. Set Up The Environment

Recommended:

```bash
./bootstrap.sh --with-tests
source .venv/bin/activate
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

## 2. Review Configuration

Open `config/config.json` and confirm:

- `project_profile`
- locale source paths
- code directories
- source and target locales

Start from `config/config.example.json` if you need a clean template.

If your project matches a built-in profile, use that profile directly. If not, use `project_profile = "auto"` or configure paths explicitly.

Recommended defaults for public and reusable setups:

- `project_profile = "auto"`
- `project_root = "."`
- `glossary_file = "docs/terminology/glossary.json"`

The bundled `docs/terminology/glossary.json` file is a small neutral example that shows the expected structure. Replace it with your own project glossary when needed.

## 3. Run The Audit

Fast pass:

```bash
./bin/run_all_audits.sh --stage fast
```

Full pass:

```bash
./bin/run_all_audits.sh --stage full
```

## 4. Inspect Results

Primary outputs:

- `Results/final/final_audit_report.md`
- `Results/review/review_queue.xlsx`
- `Results/fixes/fix_plan.json`

Per-tool outputs:

- `Results/per_tool/`

## 5. Apply Safe Fixes

Generate safe fix candidates:

```bash
./bin/run_all_audits.sh --stage autofix
```

Review:

- `Results/fixes/fix_plan.json`
- `Results/fixes/fix_plan.xlsx`
- `Results/fixes/safe_fixes_applied_report.json`

## 6. Review Human-Decision Items

Open:

- `Results/review/review_queue.xlsx`

Then:

1. review the `old_value` and `suggested_fix`
2. enter a reviewed value into `approved_new`
3. set `status` to `approved`

## 7. Apply Approved Fixes

```bash
python -m fixes.apply_review_fixes
```

Outputs:

- `Results/final_locale/ar.final.json`
- `Results/final_locale/review_fixes_report.json`

## 8. Run Tests

```bash
python -m pytest
```

## Where To Go Next

- [docs/audit_modules.md](audit_modules.md)
- [docs/review_workflow.md](review_workflow.md)
- [docs/output_reports.md](output_reports.md)
