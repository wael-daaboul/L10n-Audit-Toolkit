# Example Projects

This directory documents the supported project layouts that L10n Audit Toolkit is designed to audit. The examples are intended to show expected repository structure, locale placement, and code-usage patterns for each built-in project profile.

## Available Example Layouts

### `flutter_getx_json_sample/`

Demonstrates:

- Flutter/GetX JSON locale files under `assets/language/`
- source usage such as `'key'.tr`
- the `flutter_getx_json` project profile

### `laravel_json_sample/`

Demonstrates:

- Laravel JSON translation files
- code usage through helpers such as `__()`, `@lang()`, and `trans()`
- the `laravel_json` project profile

### `laravel_php_sample/`

Demonstrates:

- grouped Laravel PHP translation files under `resources/lang/<locale>/`
- dotted normalized keys such as `messages.login`
- the `laravel_php` project profile

### `react_i18next_json_sample/`

Demonstrates:

- JSON locale directories for React/i18next projects
- usage patterns such as `t('key')` and `i18n.t('key')`
- the `react_i18next_json` project profile

### `vue_i18n_json_sample/`

Demonstrates:

- JSON locale directories for Vue/Nuxt projects
- usage patterns such as `$t('key')`
- the `vue_i18n_json` project profile

## Running The Toolkit Against An Example

From the repository root:

1. activate the virtual environment
2. point `config/config.json` at the example project paths or use an example-specific config
3. run:

```bash
./bin/run_all_audits.sh --stage fast
```

For a full pass:

```bash
./bin/run_all_audits.sh --stage full
```

Results are generated under:

- `Results/.cache/raw_tools/`
- `Results/review/`
- `Results/final/`
- `Results/final_locale/`

## Notes

- These examples are documentation-oriented samples, not separate packages.
- The toolkit architecture stays the same across examples; only project layout, locale paths, and usage patterns differ.
