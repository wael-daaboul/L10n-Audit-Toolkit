# How To Use The Localization QA Toolkit

## What This Toolkit Does
This toolkit audits localization data and key usage across multiple project styles. It supports:
- localization usage audits
- English locale QC
- Arabic locale QC
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
Use the bootstrap script from project root:
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
- installs required dependencies
- optionally installs optional and dev dependencies
- can run schema validation
- can run tests

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
python3 -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json
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
- verify `vendor/LanguageTool-6.6`

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
