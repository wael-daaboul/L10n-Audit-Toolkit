# CAMeL Tools Integration Analysis

This document provides a comprehensive analysis of the **CAMeL Tools** shadow review layer integration within the L10n Audit Toolkit as of v1.5.4.

---

## 1. Executive Summary

CAMeL Tools is a suite of Arabic natural language processing (NLP) tools developed by the NYU Abu Dhabi CAMeL Lab. In the L10n Audit Toolkit, CAMeL Tools acts as a **shadow review layer** for Arabic translation candidates. It decorates the final review queue with deep linguistic metrics (morphological analysis, dialect identification, parts of speech, and mixed-script detection) to assist human reviewers in evaluating Arabic linguistic quality.

**Key Structural Fact**: CAMeL is **not** integrated as a standalone audit stage. Instead, it runs as a post-aggregation decorator that appends metadata to the output review queue.

---

## 2. Codebase Integration and Execution Flow

The CAMeL integration is strictly partitioned into three files in the codebase, preventing leakages into other audit stages:

```
[reports/report_aggregator.py] (Aggregation Stage)
      │
      ▼
[core/camel_decorator.py] (Appends camel_* columns to finalized review rows)
      │
      ▼
[core/arabic_nlp_layer.py] (Acts as the single integration gate with `camel-tools` library)
      ├── Real CAMeL Backend (MorphologyDB, Analyzer, DialectIdentifier)
      └── Pure-Python Fallback Backend (Unicode range scans & NFKC normalization)
```

### 2.1 Invoke Point and Timing
CAMeL analysis is invoked **at the very end of the report aggregation stage** (`reports.report_aggregator`), after:
1. All raw audit tool results are loaded and unified.
2. The initial review queue is built via `build_review_queue()`.
3. Workflow state reprojections (checking previously approved/stale items) are completed.

Once a finalized, deduplicated list of review rows is established, it is passed through `decorate_with_camel(review_rows, runtime)`. The decorated rows are then written immediately to `review_queue.xlsx`, `review_projection.json`, and `review_machine_queue.json`.

---

## 3. The Arabic NLP Layer (`arabic_nlp_layer.py`)

`l10n_audit/core/arabic_nlp_layer.py` is the isolated boundary that communicates with the `camel-tools` library.

### 3.1 Import-Time Probing
At import time, the module probes the python environment for `camel_tools`:
```python
_CAMEL_TOOLS_AVAILABLE = False
_CAMEL_TOOLS_VERSION = ""
try:
    import camel_tools
    _CAMEL_TOOLS_AVAILABLE = True
    _CAMEL_TOOLS_VERSION = getattr(camel_tools, "__version__", "unknown")
except ImportError:
    pass
```
This design makes the package **entirely optional**. The toolkit runs perfectly without `camel-tools` installed, reverting to a pure-Python fallback.

### 3.2 Pure-Python Fallback (Optional Mode)
If `_CAMEL_TOOLS_AVAILABLE` is `False`, the fallback backend executes:
* **`camel_available`**: Hardcoded to `"no"`.
* **`camel_reason`**: Set to `"camel-tools-unavailable"`.
* **`camel_mixed_script`**: Runs a pure-Python Unicode range scan. If the string contains both Arabic characters (within the `\u0600-\u06FF` range) and Latin characters (`[A-Za-z]`), it returns `"yes"`, else `"no"`.
* **`camel_unknown_count` & `camel_unknown_tokens` & `camel_pos_summary` & `camel_dialect`**: Set to `""` (cannot be computed without the morphological database).
* **`camel_normalized_preview`**: Normalizes Arabic diacritics (harakat), removes Tatweel, maps Alef variants to a bare Alef, maps Teh Marbuta to Heh, maps Alef Maksura to Yeh, translates Arabic-Indic digits to Western digits, and truncates to 120 characters.

### 3.3 Active CAMeL Backend
When the `camel-tools` library is installed, the module instantiates and queries the real pipeline. Each step is individually try/except guarded to prevent a single missing data pack from crashing the pipeline:

* **Morphological Analysis**:
  - Uses `camel_tools.morphology.database.MorphologyDB` to load the builtin database with flags `"a"` (or `"+a"` as a fallback).
  - Uses `camel_tools.morphology.analyzer.Analyzer(db)` to analyze tokens.
  - Arabic tokens are parsed; if no morphological analysis is found, the token is added to `camel_unknown_tokens`.
  - The Part-of-Speech (`pos`) tag of the first analysis is extracted and appended to `camel_pos_summary`.
* **Dialect Identification**:
  - Requires the `DialectIdentifier` data pack (downloaded via `python -m camel_tools.cli.data download`).
  - If `enable_dialect` is `True` and the model loads, `camel_tools.dialectid.DialectIdentifier.pretrained()` predicts the Arabic dialect (e.g. `MSA`, `EGY`, `LEV`, `GLF`).
* **Normalized Preview**:
  - Uses `camel_tools.utils.normalize` functions (`normalize_unicode`, `normalize_alef`, `normalize_teh_marbuta`, `normalize_alef_maksura`) to produce a clean Arabic representation.

---

## 4. Column Schema and Metadata Profile

The CAMeL integration appends exactly **8 string columns** to every review queue row. These are appended at the end of the sheet to preserve core column indices:

| Column Name | Type | Value Range / Example | Description |
|---|---|---|---|
| `camel_available` | String | `"yes"` \| `"no"` | Shows whether the real CAMeL Tools backend was active. |
| `camel_reason` | String | `"camel-tools-ok"`, `"empty-text"`, `"not-arabic-text"`, `"camel-tools-unavailable"` | Operational status note explaining why the real analyzer was or was not used. |
| `camel_mixed_script` | String | `"yes"` \| `"no"` \| `""` | Flags whether a translation contains a mix of Arabic and Latin characters. |
| `camel_unknown_count` | String | `"0"`, `"3"`, `""` | Number of Arabic word tokens that could not be morphologically resolved. |
| `camel_unknown_tokens` | String | `"برمجياتي السحابة"` | Space-joined list of unknown tokens (e.g. spelling errors, jargon, un-inflected words). |
| `camel_pos_summary` | String | `"NOUN VERB PRON PUNC"` | Unique, ordered Part-of-Speech tags present in the Arabic translation. |
| `camel_dialect` | String | `"MSA"`, `"EGY"`, `"unknown"`, `""` | Detected dialect (Modern Standard Arabic or regional dialect, if dialect ID is enabled). |
| `camel_normalized_preview` | String | `"مرحبا بك في تطبيقنا الجديد"` | NFKC normalized and Alef/Teh-Marbuta standardized text preview. |

---

## 5. Architectural Invariants and pipeline Influence

### 5.1 No Influence on Decisions
**Critical Fact**: The CAMeL Shadow Layer **never** modifies the audit results, filters rows, or changes the decision path.
* **Row Count Preservation**: The row count entering `decorate_with_camel` always matches the row count exiting it.
* **Zero Veto Power**: The safety gate (`_is_unsafe_mutation`) and decision quality projection (`_project_approved_new`) in `report_aggregator.py` run **before** CAMeL and are entirely unaware of CAMeL metrics.
* **Safety Invariant**: If any exception occurs during the analysis of a row, the decorator catches it, populates all `camel_*` fields with empty strings `""`, and proceeds. It **never** crashes a run due to a linguistic error.

### 5.2 Review Queue Contributions
While it does not affect automated decisions, CAMeL heavily influences the **Human Review** phase:
1. **Excel Visibility**: The 8 `camel_*` columns are exported directly to `review_queue.xlsx` (under `REVIEW_QUEUE_WORKBOOK_COLUMNS`). Human reviewers can use Excel filters to flag rows with high `camel_unknown_count` (potential spelling mistakes) or `camel_mixed_script == "yes"` (potential translation leakage).
2. **AI Telemetry**: The machine-consumer review files (`review_machine_queue.json`) carry these CAMeL fields. Secondary AI reviews or automated QA gates can consume these fields to score translation quality before human inspection.

---

## 6. Recommendations for the Pipeline Refactor

During the transition to the target operational pipeline, we must address the following constraints:
1. **Move to an Explicit Stage**: Decouple `decorate_with_camel` from report aggregation. It should become an explicit, independent validation stage (`CAMeL Validation`) in the execution dispatcher.
2. **Maintain Optionality**: Keep the import-time probe and the pure-Python fallback. Users must not be forced to install `camel-tools` and heavy morphological databases just to run the toolkit.
3. **Decouple from Workbook Exporters**: The Excel rendering code in `report_aggregator.py` should read the `camel_*` fields from a unified intermediate model rather than relying on the decorator to inject them directly into raw list dicts.
