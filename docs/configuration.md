# Configuration Reference

When you run `l10n-audit init`, the toolkit automatically creates a `.l10n-audit` directory in your project root containing a `config.json` file. 

This file is the single source of truth for how the audit toolkit interacts with your specific codebase. While the toolkit attempts to auto-detect your framework, you can always manually tune these parameters.

## The `config.json` Structure

A standard, fully expanded configuration file looks like this:

```json
{
  "project_profile": "laravel_json",
  "locale_format": "json",
  "locale_root": "resources/lang",
  "locale_paths": [
    "resources/lang/{locale}.json"
  ],
  "source_locale": "en",
  "target_locales": [
    "ar"
  ],
  "code_dirs": [
    "app",
    "resources/views",
    "routes"
  ],
  "usage_patterns": [
    "__\\(['\"](.*?)['\"]\\)",
    "@lang\\(['\"](.*?)['\"]\\)",
    "trans\\(['\"](.*?)['\"]\\)"
  ],
  "languagetool_dir": null,
  "glossary_file": "docs/terminology/glossary.json"
}
```

## Parameter Explained

### `project_profile` (string)
The master template. If set to `"auto"`, the toolkit will try to guess your framework based on marker files (like `artisan` or `pubspec.yaml`).
**Available Built-in Profiles:**
- `flutter_getx_json`
- `laravel_json`
- `laravel_php`
- `react_i18next_json`
- `vue_i18n_json`
- `auto`

*Note: If `project_profile` is a valid string (not "auto"), the toolkit will prioritize this profile's defaults.*

### `locale_format` (string)
Defines how the toolkit reads and parses the language files.
**Options:**
- `"json"`: Standard key-value JSON parsing.
- `"laravel_php"`: Parses static PHP arrays (e.g., `return ['key' => 'value'];`).

### `locale_root` / `locale_paths` (string / array)
Tells the toolkit where to find the translation files. 
- **For PHP arrays (`laravel_php`)**: Use `locale_root` pointing to the directory (e.g., `"resources/lang"`). The tool expects subfolders named by locale (e.g., `resources/lang/en/`).
- **For JSON (`json`)**: Use `locale_paths`. You must use the `{locale}` placeholder in the path (e.g., `"resources/lang/{locale}.json"` or `"assets/i18n/{locale}.json"`).

### `source_locale` (string)
The primary language of your application (usually `"en"`). All translations, grammar, and missing keys are compared against this locale.

### `target_locales` (array of strings)
The languages you are auditing. Example: `["ar", "fr"]`. *Note: Semantic and QC audits Currently have specific deep support for `"ar"` (Arabic).*

### `code_dirs` (array of strings)
A list of directories the usage scanner should search through to find where translation keys are called. Limiting this to your actual app folders (e.g., `["lib"]` for Flutter or `["app", "resources"]` for Laravel) drastically improves scan speed and reduces false positives.

### `usage_patterns` (array of strings)
Regular expressions used to find static translation calls in your code. 
- You typically don't need to touch this if you use a built-in `project_profile`.
- If you use a custom wrapper function (e.g., `translateText('Hello')`), you can append your custom regex here.
- The regex must capture the translation key in its **first capturing group** `(.*?)`.

### `languagetool_dir` (string | null)
If you have downloaded a local standalone Java version of LanguageTool for faster and offline English grammar checking, specify the path to its directory here. If `null`, the toolkit will attempt to auto-discover it in `vendor/LanguageTool-*` or use the Python bridge.

### `glossary_file` (string)
Path to your approved terminology file (JSON format). Relative to your project root. Defaults to `"docs/terminology/glossary.json"`.

---

## Overriding vs. Profile Defaults

When `l10n-audit init` generates the workspace, it maps the chosen `project_profile` fields into `config.json`. 

You can manually change any of these fields. **Explicit fields defined in `config.json` will ALWAYS override the implicit defaults of the `project_profile`.**

For instance, if your Next.js app has locales in `public/locales` instead of `src/locales`, you simply edit `locale_paths` in `config.json`, and the toolkit will respect your custom path while keeping the rest of the React/Next.js intelligence intact.

---

## Environment Variable Flags

The following environment variables control optional runtime behaviors. They are not stored in `config.json` and do not affect the audit contract.

### `L10N_AUDIT_DEBUG_AI`

Enables verbose AI diagnostics mode.

```bash
export L10N_AUDIT_DEBUG_AI=1
```

When set to `1`, `true`, `yes`, or `on`:
- Raw LiteLLM and provider stdout/stderr output is preserved (not suppressed).
- Detailed per-attempt provider error traces are emitted to the log.
- Fallback and skip reason codes are logged for every AI decision.

Default: unset (normal mode — LiteLLM output suppressed, toolkit logs visible).

### `L10N_AUDIT_CANONICAL_SOURCE_GUARD_DISABLE`

Disables the canonical source guard. **Not recommended for production.**

```bash
export L10N_AUDIT_CANONICAL_SOURCE_GUARD_DISABLE=1
```

The canonical source guard (enabled by default in v1.7.1) enforces deterministic source-identity across audit runs, preventing source-key drift during AI review and apply operations. Disabling it may allow stale or diverged source values to propagate into the fix pipeline.
