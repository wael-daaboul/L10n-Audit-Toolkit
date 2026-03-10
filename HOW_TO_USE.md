# How To Use The Localization QA Toolkit

This guide documents the standard audit, review, approved-fix, and final-locale workflow. For output details, see [docs/output_reports.md](docs/output_reports.md). For fix integrity and review queue behavior, see [docs/review_workflow.md](docs/review_workflow.md).

## Workflow

### English

Step 1 - Run the audit

```bash
l10n-audit init
l10n-audit run --stage full
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
l10n-audit init
l10n-audit run --stage full
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

## Context-Aware Review

### English

The toolkit now compares the key, the English source value, the Arabic target value, and inferred usage context from code before making meaning-sensitive review decisions.

LanguageTool and `language-tool-python` remain part of the linguistic review path. Their signals help with grammar, style, punctuation, and literalness suspicion, but they do not decide person-versus-department or role-versus-entity meaning by themselves.

When the toolkit detects context-sensitive ambiguity, it keeps the finding as `review_required` and explains the risk in the review queue.

### العربية

يقارن النظام الآن بين اسم المفتاح والقيمة الإنجليزية والقيمة العربية لنفس المفتاح، ويحاول أيضاً استنتاج مكان استخدام النص داخل الواجهة من الكود قبل اتخاذ أي قرار دلالي حساس.

ما زال LanguageTool و `language-tool-python` جزءاً من مسار المراجعة اللغوية. وتُستخدم إشاراتهما لدعم فحص القواعد والأسلوب والترقيم والتنبيه إلى الصياغة الحرفية، لكنهما لا يقرران وحدهما ما إذا كانت الكلمة تشير إلى شخص أو إدارة أو دور أو كيان.

وعندما يكتشف النظام غموضاً دلالياً مرتبطاً بالسياق، فإنه يبقي الحالة على `review_required` ويشرح سبب ذلك داخل ملف المراجعة.

## LanguageTool Behavior

### English

The toolkit first looks for a local LanguageTool installation in the project.

- It does not depend on a fixed version like `LanguageTool-6.6`.
- It accepts any local directory named `LanguageTool-*`.
- Preferred discovery locations are `tools/vendor/` and `vendor/`.
- If found, it uses the local installation directly.
- If not found, it falls back to `language-tool-python`, which may download LanguageTool once and cache it.

Optional override:

```json
{
  "languagetool_dir": "tools/vendor/LanguageTool-7.0"
}
```

### العربية

تحاول الأداة أولاً العثور على نسخة محلية من LanguageTool داخل المشروع.

- لا تعتمد الأداة على رقم إصدار ثابت مثل `LanguageTool-6.6`.
- يكفي وجود مجلد محلي باسم مشابه لـ `LanguageTool-*`.
- أماكن البحث المفضلة هي `tools/vendor/` و `vendor/`.
- إذا وجدته الأداة، تستخدمه مباشرة.
- إذا لم تجده، تنتقل إلى السلوك الاحتياطي عبر `language-tool-python`، والذي قد يقوم بتحميل LanguageTool مرة واحدة ثم تخزينه مؤقتاً.

## What This Toolkit Does
This toolkit audits localization data and key usage across multiple project styles. It supports:
- localization usage audits
- English locale QC
- Arabic locale QC
- Arabic semantic review suggestions
- terminology validation
- placeholder validation
- ICU message validation
- final aggregated reporting
- safe fix planning
- schema validation
- regression tests

## Supported Project Types
Current built-in profiles:
- `flutter_getx_json`
- `laravel_json`
- `laravel_php`
- `react_i18next_json`
- `vue_i18n_json`

## Supported Locale Formats
- JSON locale files
- Laravel PHP translation files with safe static parseable return structures such as `return [...]` and `return array(...)`

Unsupported in the current phase:
- dynamic PHP translation logic
- non-JSON formats beyond Laravel PHP arrays
- AST-based framework parsing

## Arabic Semantic Review

### English

Run the standalone semantic review module when you want reviewer-facing Arabic rewrite suggestions without mixing them into deterministic QC:

```bash
python -m audits.ar_semantic_qc
```

This module writes:

- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.json`
- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.csv`
- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.xlsx`

Typical output includes:

- `possible_meaning_loss`
- `sentence_shape_mismatch`
- `message_label_mismatch`
- review-only `candidate_value` suggestions

These suggestions are not auto-applied. They are intended for human review.

### العربية

يمكنك تشغيل فحص المراجعة الدلالية العربي بشكل مستقل عندما تحتاج إلى اقتراحات صياغة للمراجع البشري دون خلطها مع إصلاحات التنسيق الحتمية:

```bash
python -m audits.ar_semantic_qc
```

سيُنتج هذا الفحص الملفات التالية:

- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.json`
- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.csv`
- `Results/per_tool/ar_semantic_qc/ar_semantic_qc_report.xlsx`

ومن أمثلة النتائج:

- `possible_meaning_loss`
- `sentence_shape_mismatch`
- `message_label_mismatch`
- اقتراحات `candidate_value` للمراجعة فقط

هذه الاقتراحات لا تُطبَّق تلقائياً، بل تبقى ضمن مسار المراجعة البشرية.

## How Project Profiles Work
Profiles define:
- locale format
- locale source conventions
- source and target locales
- code directory candidates
- usage detection patterns
- allowed source file extensions

## Static vs Dynamic Translation Detection
The localization usage audits now distinguish:
- static translation usage
  - string-literal calls that can be mapped to a concrete locale key
- dynamic translation usage
  - variable or expression-based calls that cannot be mapped safely

Dynamic translation calls are reported separately and do not count toward static detected-key totals.

Examples treated as static:
- `translate('Add')`
- `translate(key: 'Home')`
- `__('validation.required')`
- `@lang('messages.saved')`
- `'home.title'.tr`
- `t('common.save')`
- `$t('nav.home')`

Examples treated as dynamic:
- `translate($key)`
- `translate(key: $notification['title'])`
- `__($key)`
- `trans($value)`
- `tr(variable)`
- `t(keyVar)`
- `$t(keyVar)`

Built-in profiles live in:
- `config/project_profiles.json`

Project-level configuration lives in:
- `config/config.json`
- `config/config.example.json`

The glossary filename itself is not fixed. Any JSON filename is supported if `glossary_file` points to it. For new projects, `docs/terminology/glossary.json` is the recommended neutral name.

The repository's `docs/terminology/glossary.json` file is only a small structural example. Replace it with your own glossary data for real projects.

Recommended launcher workflow for real projects:

```bash
l10n-audit init
l10n-audit doctor
l10n-audit run --stage full
l10n-audit update --check
l10n-audit update --from-github --channel stable --repo https://github.com/your-org/l10n-audit-toolkit
```

Public extension point:
- profiles and project config can extend static helper detection through `usage_patterns`
- custom string-literal patterns should use a `KEY` placeholder when configured manually

## Manual Profile Configuration
Manual configuration is authoritative.

Example:
```json
{
  "project_profile": "laravel_php",
  "locale_format": "laravel_php",
  "locale_root": "resources/lang",
  "source_locale": "en",
  "target_locales": ["ar"],
  "code_dirs": ["app", "resources/views", "routes"]
}
```

If `project_profile` is set to a real profile name, the toolkit will not override it.

## Auto Profile Detection
Autodetection runs when:
- `project_profile` is set to `"auto"`
- or `project_profile` is omitted

The detector scores each supported profile using:
- marker files such as `pubspec.yaml`, `artisan`, or `package.json`
- locale file/folder evidence
- code directory evidence
- source file extension evidence
- lightweight framework usage hints

If confidence is too low or ambiguous, the toolkit stops and asks you to set `project_profile` manually.

## Bootstrap the Environment
Use the bootstrap script from project root. For many users this is the preferred first step:
```bash
./bootstrap.sh
```

Useful flags:
```bash
./bootstrap.sh --with-tests
./bootstrap.sh --skip-optional
./bootstrap.sh --validate-schemas
./bootstrap.sh --run-tests
```

The bootstrap script:
- creates `.venv` if missing
- upgrades `pip`
- installs required dependencies
- optionally installs optional and dev dependencies
- can run schema validation
- can run tests

Manual setup is still supported when you want to install dependencies step by step yourself.

## Run Audits
Fast audit:
```bash
./bin/run_all_audits.sh --stage fast
```

Full audit:
```bash
./bin/run_all_audits.sh --stage full
```

Specific stages:
```bash
./bin/run_all_audits.sh --stage grammar
./bin/run_all_audits.sh --stage terminology
./bin/run_all_audits.sh --stage placeholders
./bin/run_all_audits.sh --stage ar-qc
./bin/run_all_audits.sh --stage icu
./bin/run_all_audits.sh --stage reports
./bin/run_all_audits.sh --stage autofix
```

## Run Tests
From the repository root:
```bash
python3 -m pytest tests
```

## Validate Schemas
From the repository root:
```bash
python3 -m core.schema_validation --input config/config.json --schema schemas/config.schema.json
python3 -m core.schema_validation --input docs/terminology/<your-glossary-file>.json --schema schemas/glossary.schema.json
```

After generating audit outputs, you can validate the full built-in contract set:
```bash
python3 -m core.schema_validation --preset core
```

## Results Layout
Canonical outputs are stored under:
- `Results/per_tool/`
- `Results/normalized/`
- `Results/final/`
- `Results/fixes/`
- `Results/exports/`

Per-tool outputs remain separate from final aggregated reports.

## How Fix Plans Work
Safe fix planning generates:
- `Results/fixes/fix_plan.json`
- `Results/fixes/fix_plan.xlsx`
- candidate locale outputs such as `en.fixed.json` and `ar.fixed.json`
- source-format exports under `Results/exports/`

Only safe formatting fixes are auto-applied in candidate outputs. Content-heavy changes remain `review_required`.

## Exported Locale Files
The toolkit can export fixed locale mappings back into the selected source format under `Results/exports/`.

For JSON projects:
- `Results/exports/en.json`
- `Results/exports/ar.json`

For Laravel PHP projects:
- `Results/exports/en/lang.php`
- `Results/exports/ar/lang.php`
- `Results/exports/en/messages.php`
- `Results/exports/ar/messages.php`
- `Results/exports/en/validation.php`

Laravel PHP export behavior:
- grouped keys like `lang.Add` go back to `lang.php`
- dotted keys like `messages.auth.failed` become nested arrays
- output uses deterministic modern PHP syntax with `return [ ... ];`

Safety guarantees:
- source locale files are not overwritten by default
- exports are generated only under `Results/exports/`
- values are preserved exactly from the fixed mapping

## Framework-Specific Notes

### Flutter / GetX JSON
Typical profile:
- `flutter_getx_json`

Typical layout:
- `assets/language/en.json`
- `assets/language/ar.json`
- `lib/`

Usage patterns:
- `'key'.tr`
- `tr('key')`

### Laravel JSON
Typical profile:
- `laravel_json`

Typical layout:
- `resources/lang/en.json`
- `resources/lang/ar.json`
- `app/`
- `resources/views/`
- `routes/`

Usage patterns:
- `__('key')`
- `@lang('key')`
- `trans('key')`

### Laravel PHP
Typical profile:
- `laravel_php`

Typical layout:
- `resources/lang/en/messages.php`
- `resources/lang/en/validation.php`
- `resources/lang/ar/messages.php`

Flattening strategy:
- file stem becomes the group prefix
- nested arrays become dotted keys
- `messages.php` + `['login' => 'Login']` becomes `messages.login`

Laravel helper alignment:
- native helper calls such as `__('lang.Add')` are matched as-is
- custom helper calls such as `translate('Add')` are normalized only when the loaded locale catalog contains a matching grouped key like `lang.Add`
- this alignment is profile-aware and intentionally conservative
- dynamic helper calls are reported separately and do not count as static matches

Only safe static parseable translation return structures such as `return [...]` and `return array(...)` are supported.

### React / Next JSON
Typical profile:
- `react_i18next_json`

Typical layout:
- `locales/en.json`
- `public/locales/en.json`
- or `src/locales/en.json`

Usage patterns:
- `t('key')`
- `i18n.t('key')`

### Vue / Nuxt JSON
Typical profile:
- `vue_i18n_json`

Typical layout:
- `locales/en.json`
- or `src/locales/en.json`

Usage patterns:
- `$t('key')`

## Common Troubleshooting
If autodetection is ambiguous:
- set `project_profile` manually in `config/config.json`

If locale files are not in the default locations:
- set `locale_paths` for JSON projects
- set `locale_root` for Laravel PHP projects

If code is scanned in the wrong directories:
- set `code_dirs` explicitly

If grammar audit is shallow:
- verify Java
- verify a local `LanguageTool-*` directory under `tools/vendor/` or `vendor/`, or allow the `language-tool-python` fallback to initialize

If fixture tests fail in a copied project:
- ensure the audit is being run with explicit fixture paths
- ensure dev dependencies are installed

## When You Should Set Config Manually
Set config manually when:
- autodetection is ambiguous
- your project layout is non-standard
- your locale files live in custom paths
- you want to override code scanning directories
- you want to pin a profile explicitly for CI stability

## Important Commands
```bash
./bootstrap.sh --with-tests
./bin/run_all_audits.sh --stage fast
./bin/run_all_audits.sh --stage full
python3 -m core.schema_validation --preset core
python3 -m pytest tests
```
