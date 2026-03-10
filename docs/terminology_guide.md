# Terminology & Glossary Format Guide

The L10n Audit Toolkit enforces approved product vocabulary and detects forbidden terms using the `terminology_audit` module. This check is driven by a `glossary.json` file.

This document explains how to perfectly structure your terminology file.

## The `glossary.json` Structure

By default, the toolkit expects this file at `docs/terminology/glossary.json`. You can point to a different location in your `.l10n-audit/config.json` via the `glossary_file` property.

The JSON structure is an array of objects. Each object represents a single linguistic rule.

```json
[
  {
    "term": "cart",
    "translation": "عربة التسوق",
    "forbidden_terms": ["السلة", "حقيبة المشتريات", "عربة"],
    "context": "E-commerce shopping cart, not a physical vehicle."
  },
  {
    "term": "checkout",
    "translation": "إتمام الطلب",
    "forbidden_terms": ["الدفع", "تسجيل الخروج"],
    "context": "The action of finalizing an order."
  },
  {
    "term": "login",
    "translation": "تسجيل الدخول",
    "forbidden_terms": ["دخول", "الولوج", "تسجيل دخول"],
    "context": "Authentication action. Must include 'تسجيل'."
  }
]
```

## Available Fields

### `term` (string)
**Required.** The English source word or phrase you want to monitor. 

The terminology engine is **case-insensitive** but strictly checks for whole words. It will map `"login"` to `Login`, `login`, and `LOGIN` in your English locale file automatically.

### `translation` (string)
**Required.** The exact approved Arabic (or target language) translation that must be used whenever the English `term` appears.

### `forbidden_terms` (array of strings)
*Optional, but highly recommended.*
A list of specific Arabic words that translators commonly use by mistake, but are officially banned for this context. 

If the English string contains the `term`, and the Arabic string contains ANY word from `forbidden_terms`, the toolkit will immediately flag a **Hard Violation** (`terminology_violation`). This prevents "glossary drift."

### `context` (string)
*Optional.*
A human-readable explanation of why this term requires a specific translation. This helps reviewers understand the rule when they see the violation in the `review_queue.xlsx`.

## Violation Types

The `terminology_audit` will emit two classes of findings:

1. **`terminology_violation` (Hard Error):**
   - The English source contained the exact `term`.
   - The Arabic target contained an exact match from `forbidden_terms`.
   - This is considered a critical error.

2. **`terminology_drift` (Warning):**
   - The English source contained the exact `term`.
   - The Arabic target did **not** contain the exact `translation`.
   - The Arabic target did **not** contain a forbidden term.
   - This may be an acceptable contextual change (e.g., grammar inflection), but it's flagged for a human to review to ensure the brand vocabulary isn't drifting.

## Best Practices

1. **Keep `forbidden_terms` specific:** Do not ban extremely common Arabic prepositions. Only ban words that are the *direct, wrong synonyms* for the English word.
2. **Exclude dynamic phrases:** The parser works best on static nouns and common UI verbs (e.g., Setup, Sync, Account, Password). Do not put full sentences in the glossary.
3. **Use the Review Queue:** If a `terminology_drift` is actually a correct grammatical variation (like adding "الـ" or a plural form), simply click "Approve" in the review queue. The toolkit prefers human oversight over stripping out valid Arabic conjugations.
