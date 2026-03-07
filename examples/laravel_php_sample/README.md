# Laravel PHP Sample

This placeholder example documents the intended structure for a minimal Laravel project that stores translations in PHP files such as:

- `resources/lang/en/messages.php`
- `resources/lang/en/validation.php`
- `resources/lang/ar/messages.php`

The matching toolkit profile is `laravel_php`.

Expected behaviors for this sample:
- locale loading flattens PHP arrays into dotted keys like `messages.login`
- usage scanning detects grouped Laravel translation usage such as `__('messages.login')`
- audits run on normalized locale mappings without duplicating audit logic
