# L10n Audit Toolkit

Cross-framework localization audit and translation QA tooling for Python-based repository workflows.

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Status: Active](https://img.shields.io/badge/status-active-success)

L10n Audit Toolkit is a cross-framework localization auditing toolkit written in Python. It helps teams review localization, i18n, translation QA, and localization audit results by analyzing locale files and translation usage in source code before release.

## Workflow

### English

Step 1 - Run the audit

```bash
./bin/run_all_audits.sh --stage full
```

Step 2 - Open the dashboard

Open `Results/final/final_audit_report.md`

This report shows:
- total issues
- critical problems
- safe fixes available
- review required issues

Step 3 - Review human-decision items

Open `Results/review/review_queue.xlsx`

Edit the `approved_new` column, then set `status = approved`.

Step 4 - Apply reviewed fixes

```bash
python -m fixes.apply_review_fixes
```

Step 5 - Export final localization

The final file will appear in `Results/final_locale/ar.final.json`

This file is the cleaned and reviewed localization file ready for use.

### العربية

الخطوة 1 - تشغيل التدقيق

```bash
./bin/run_all_audits.sh --stage full
```

الخطوة 2 - فتح التقرير الرئيسي

افتح الملف `Results/final/final_audit_report.md`

سيعرض هذا التقرير:
- عدد المشاكل الكلي
- المشاكل الحرجة
- الإصلاحات التلقائية المتاحة
- العناصر التي تحتاج مراجعة بشرية

الخطوة 3 - مراجعة العناصر التي تحتاج قراراً بشرياً

افتح الملف `Results/review/review_queue.xlsx`

قم بتعديل العمود `approved_new` ثم ضع في عمود الحالة `status = approved`

الخطوة 4 - تطبيق التعديلات المعتمدة

```bash
python -m fixes.apply_review_fixes
```

الخطوة 5 - الحصول على ملف الترجمة النهائي

سيتم إنشاء الملف النهائي في `Results/final_locale/ar.final.json`

وهذا الملف هو نسخة الترجمة النظيفة الجاهزة للاستخدام في التطبيق.

## LanguageTool Setup

### English

The toolkit first looks for a local LanguageTool installation in the project.

- It does not depend on a hardcoded version number.
- It accepts any discovered `LanguageTool-*` directory.
- Preferred search locations are `tools/vendor/` and `vendor/`.
- If a local installation is found, the toolkit uses it directly.
- If not found, it falls back to `language-tool-python`, which may download LanguageTool once and cache it.

Optional override in `config/config.json`:

```json
{
  "languagetool_dir": "tools/vendor/LanguageTool-7.0"
}
```

This helps keep the GitHub repository smaller because users can keep LanguageTool local without committing a large bundled directory.

### العربية

تحاول الأداة أولاً العثور على نسخة محلية من LanguageTool داخل المشروع.

- لا تعتمد الأداة على رقم إصدار ثابت مثل `LanguageTool-6.6`.
- يكفي وجود مجلد محلي باسم مشابه لـ `LanguageTool-*`.
- أماكن البحث المفضلة هي `tools/vendor/` و `vendor/`.
- إذا وجدته الأداة، تستخدمه مباشرة.
- إذا لم تجده، تنتقل إلى السلوك الاحتياطي عبر `language-tool-python`، والذي قد يقوم بتحميل LanguageTool مرة واحدة ثم تخزينه مؤقتاً.

ويساعد هذا السلوك على إبقاء المستودع أخف على GitHub لأن المستخدم يمكنه وضع LanguageTool محلياً دون الحاجة إلى إضافته إلى المستودع.

## Bootstrap

### English

`bootstrap.sh` is the recommended first step for many users.

It:
- creates `.venv`
- upgrades `pip`
- installs required dependencies
- optionally installs optional and development dependencies
- can validate schemas
- can run tests

Examples:

```bash
./bootstrap.sh
./bootstrap.sh --with-tests
./bootstrap.sh --validate-schemas
./bootstrap.sh --run-tests
```

Use manual setup only when you want tighter control over each installation step.

### العربية

يُعد `bootstrap.sh` خطوة أولى مفضلة لكثير من المستخدمين.

وهو يقوم بـ:
- إنشاء `.venv`
- ترقية `pip`
- تثبيت المتطلبات الأساسية
- تثبيت المتطلبات الاختيارية ومتطلبات التطوير عند الحاجة
- تشغيل التحقق من المخططات عند الطلب
- تشغيل الاختبارات عند الطلب

أمثلة:

```bash
./bootstrap.sh
./bootstrap.sh --with-tests
./bootstrap.sh --validate-schemas
./bootstrap.sh --run-tests
```

أما الإعداد اليدوي فهو مناسب عندما تريد التحكم بكل خطوة بشكل مباشر.

## Context-Aware Review

### English

The toolkit now evaluates localization review using:
- the key name
- the English value
- the Arabic value
- inferred UI usage context from code
- linguistic support signals from LanguageTool and `language-tool-python`

LanguageTool remains part of the linguistic review path for grammar, style, punctuation, and literalness hints.

Semantic decisions are guarded separately. If a replacement may confuse a person, role, department, team, or system area, the toolkit keeps the issue as `review_required` and does not auto-apply the replacement.

### العربية

يعتمد التدقيق الآن على:
- اسم المفتاح
- النص الإنجليزي
- النص العربي
- محاولة استنتاج مكان استخدام النص داخل الواجهة من الكود
- إشارات لغوية مساندة من LanguageTool و `language-tool-python`

ما زال LanguageTool جزءاً أساسياً من مسار المراجعة اللغوية من أجل القواعد والأسلوب وعلامات الترقيم والتنبيه إلى الصياغة الحرفية.

لكن القرارات الدلالية لا تُتخذ آلياً. إذا وُجد احتمال خلط بين شخص أو دور أو إدارة أو قسم أو مساحة داخل النظام، فسيتم إبقاء الحالة على `review_required` ولن يطبّق النظام هذا الاستبدال تلقائياً.

## Features

- Automatic project type detection for supported frameworks
- Localization key usage scanning in application source code
- Detection of unused localization keys
- Detection of missing translations
- Placeholder mismatch detection
- Terminology validation against a glossary
- English grammar checking with local-first LanguageTool discovery and `language-tool-python` fallback
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

Recommended quick setup:

```bash
./bootstrap.sh
source .venv/bin/activate
./bin/run_all_audits.sh --stage fast
```

Manual setup:

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
- `vendor/LanguageTool-*/` or `tools/vendor/LanguageTool-*/`: optional local LanguageTool installations

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
- Java for deeper grammar checking when using local LanguageTool or the `language-tool-python` fallback

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

You can also bootstrap the environment with the repository script. For many users this is the preferred first setup step:

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
