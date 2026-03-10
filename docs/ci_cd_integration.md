# CI/CD Integration Guide

Running the L10n Audit Toolkit inside your Continuous Integration (CI) pipeline ensures that localization issues (like broken placeholders, forbidden terminology, or missing keys) are caught *before* they are merged into your main branch.

This guide provides drop-in templates for integrating `l10n-audit` into popular CI/CD platforms.

## General CI Strategy

In a CI environment, you typically want to:
1. **Run a fast or full audit** on every Pull Request.
2. **Fail the build** if critical errors are found.
3. **Generate Reports** that can be read by developers or uploaded as CI Artifacts.
4. **Skip AI and Autofixing** to maintain a deterministic, fast, and read-only pipeline.

---

## 🚀 GitHub Actions

Create a new workflow file in your repository at `.github/workflows/l10n-audit.yml`.

### Example: Basic PR Verification
This workflow runs every time a developer opens or updates a Pull Request.

```yaml
name: Localization Audit

on:
  pull_request:
    branches: [ "main", "master", "develop" ]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install pipx (if not pre-installed)
        run: python -m pip install --upgrade pipx

      - name: Install L10n Audit Toolkit
        run: pipx install git+https://github.com/wael-daaboul/L10n-Audit-Toolkit.git

      - name: Initialize Workspace
        run: l10n-audit init --force

      - name: Run Localization Audit (Full Stage)
        run: l10n-audit run --stage full

      - name: Upload Audit Reports
        if: always() # Upload reports even if the audit fails
        uses: actions/upload-artifact@v4
        with:
          name: l10n-audit-results
          path: Results/
          retention-days: 7
```

### Advanced: AI-Powered Nightly Audits
If you want to use the AI review features automatically, it's best to run them on a schedule (e.g., nightly) rather than on every PR to save costs and API limits.

```yaml
name: Nightly AI Localization Review

on:
  schedule:
    - cron: '0 2 * * *' # Runs at 02:00 AM daily

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install L10n Audit Toolkit
        run: pipx install git+https://github.com/wael-daaboul/L10n-Audit-Toolkit.git
        
      - name: Initialize Workspace
        run: l10n-audit init --force

      - name: Run AI Review
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
        run: |
          l10n-audit run --stage ai-review \
            --ai-enabled \
            --ai-api-base "https://openrouter.ai/api/v1" \
            --ai-model "openai/gpt-4o-mini"
            
      - name: Upload AI Review Queue
        uses: actions/upload-artifact@v4
        with:
          name: ai-review-queue
          path: Results/review/
```

---

## 🦊 GitLab CI

Create or update your `.gitlab-ci.yml` in the root of your repository.

### Example: Basic PR Verification

```yaml
stages:
  - test

l10n-audit-job:
  stage: test
  image: python:3.11-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  before_script:
    - apt-get update && apt-get install -y git default-jre
    - python -m pip install --upgrade pip pipx
    - pipx ensurepath
    - source ~/.bashrc || true
    - pipx install git+https://github.com/wael-daaboul/L10n-Audit-Toolkit.git
  script:
    - /root/.local/bin/l10n-audit init --force
    - /root/.local/bin/l10n-audit run --stage full
  artifacts:
    when: always
    paths:
      - Results/
    expire_in: 1 week
```
*(Note: `default-jre` is installed to support local LanguageTool grammar checks if present).*

---

## Handling Exit Codes

The `l10n-audit run` command is designed to return a non-zero exit code (e.g., `exit 1`) if critical errors (like formatting breaks or missing placeholders) are found. This naturally fails the CI pipeline job, preventing faulty translations from being deployed.

If you ever want to run the audit purely for generating reports *without* failing the build, you can use standard shell mechanics to bypass the exit code:

```bash
l10n-audit run --stage full || true
```
