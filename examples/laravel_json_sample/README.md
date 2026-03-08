# Laravel JSON Sample

This example documents the expected layout for a Laravel project that stores translations in JSON locale files.

## What It Demonstrates

- locale files such as `resources/lang/en.json`
- code scanning across `app/`, `resources/views/`, and `routes/`
- Laravel helper usage such as `__('key')`, `@lang('key')`, and `trans('key')`
- the `laravel_json` project profile

## How To Use It

Configure the toolkit for the sample project and run:

```bash
./bin/run_all_audits.sh --stage fast
```

Laravel PHP array translation files are covered separately by `laravel_php_sample/`.
