# Laravel PHP Sample

This example documents the expected structure for a Laravel project that stores translations in grouped PHP files.

## What It Demonstrates

- translation files such as:
  - `resources/lang/en/messages.php`
  - `resources/lang/en/validation.php`
  - `resources/lang/ar/messages.php`
- the `laravel_php` project profile
- normalized dotted keys such as `messages.login`
- grouped helper usage such as `__('messages.login')`

## Expected Behaviors

- locale loading flattens PHP arrays into dotted keys like `messages.login`
- usage scanning detects grouped Laravel translation usage such as `__('messages.login')`
- audits run on normalized locale mappings without duplicating audit logic

## How To Use It

Run the standard workflow after configuring the sample paths:

```bash
./bin/run_all_audits.sh --stage fast
```
