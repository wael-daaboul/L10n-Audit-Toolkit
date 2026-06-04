# Pipeline Refactor Plan — Target Operational Workflow

**Document Class:** Pipeline Refactor Plan & Migration Roadmap  
**Target Version:** v2.0.0-alpha  
**Refactor Type:** Architectural & Dispatcher Refactor (Analysis Only)  
**Status:** PROPOSED — awaiting developer and stakeholder review.

---

## 1. Current State vs. Problems

### 1.1 Current State
In the current implementation (v1.5.4), audit execution is divided into ad-hoc CLI "stages" that co-mingle operational goals with specific audit tools:
* `fast`: A compound stage running a hardcoded suite of linguistic and technical checks, followed by report aggregation.
* `full`: A compound stage running `fast` audits plus `en_grammar_audit` (LanguageTool) and `icu_message_audit`.
* Ad-hoc stages (`grammar`, `terminology`, `placeholders`, `ar-qc`, `ar-semantic`, `icu`): Run individual, isolated Python files.
* `reports`: Runs the aggregator over previously generated JSONs.
* `autofix`: Invokes immediate mechanical fixes via `fixes.apply_safe_fixes`.
* `ai-review`: Invokes LLM-based suggestion generation.

### 1.2 Problems with Current Stage Layout
1. **Audit Type vs. Operational Phase**: Stages are defined by *what* tool runs rather than *where* it fits in the localization lifecycle.
2. **Co-mingled Scan & Analysis**: The scanning of the source code (Project Scan) is combined with linguistic validation (Linguistic QC).
3. **Implicit CAMeL Integration**: CAMeL is buried inside the `report_aggregator.py` step instead of running as a distinct validation stage. It is impossible to run CAMeL alone without generating reports or building the review queue.
4. **Scattered Technical Checks**: Placeholder and ICU message validations are separate commands rather than a single, unified "Technical Validation" gate.
5. **No Independent Pipeline Controls**: CI/CD pipelines cannot easily execute validation stages in isolation without triggering report file writes and archiving steps.

---

## 2. Proposed Stage Layout (The 9 Logical Stages)

We propose organizing the toolkit's pipeline into **9 clear operational stages**. This maps every existing audit, component, and utility to its logical home without changing their internal logic.

```
┌────────────────────────────────────────────────────────┐
│                   1. Project Scan                      │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                 2. English Validation                  │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                3. Technical Validation                 │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│               4. Translation Generation                │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                 5. Arabic Validation                   │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                  6. CAMeL Validation                   │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                     7. Reporting                       │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                   8. Human Review                      │
└───────────────────────────┬────────────────────────────┘
                            ▼
┌────────────────────────────────────────────────────────┐
│                       9. Apply                         │
└────────────────────────────────────────────────────────┘
```

| # | Operational Stage | Description | Component / Audit Mapping |
|---|---|---|---|
| **1** | **Project Scan** | Discovers framework profile, scans source code for localizable keys, and builds key inventory. | `audits.l10n_audit_pro` |
| **2** | **English Validation** | Inspects English source strings for spelling, casing, whitespace, and grammatical violations. | `audits.en_locale_qc`<br>`audits.en_grammar_audit` (LanguageTool) |
| **3** | **Technical Validation** | Ensures non-translatable tokens, variables, and formats align across languages. | `audits.placeholder_audit`<br>`audits.icu_message_audit`<br>`audits.basic_consistency_audit` |
| **4** | **Translation Generation** | Suggests translation candidates for missing keys or phrasing improvements using AI. | `audits.ai_review` |
| **5** | **Arabic Validation** | Evaluates target Arabic translation strings against glossary, style, and semantic rules. | `audits.ar_locale_qc`<br>`audits.ar_semantic_qc`<br>`audits.terminology_audit` |
| **6** | **CAMeL Validation** | Executes Arabic NLP morphological, part-of-speech, and dialectical analysis. | `core/camel_decorator.py`<br>`core/arabic_nlp_layer.py` |
| **7** | **Reporting** | Combines all validation logs and issues into final user-facing reports and workspaces. | `reports.report_aggregator` |
| **8** | **Human Review** | Mediates human review reconciliation and freezes approved suggestions. | `fixes.fix_merger` (CLI: `prepare-apply`) |
| **9** | **Apply** | Writes frozen human approvals and safe auto-fixes back into original locale files. | `fixes.apply_review_fixes` (CLI: `apply`) <br> `fixes.apply_safe_fixes` (CLI: `autofix`) |

---

## 3. Explicit Answers to Architectural Questions

### 3.1 Can existing audits be reused without modification?
**Yes.** All current audit modules (`en_locale_qc`, `ar_locale_qc`, `terminology_audit`, etc.) are written as standalone, pure-Python modules that expose a standardized signature:
```python
def run_stage(runtime, options, *, en_data=None, ar_data=None) -> list[AuditIssue]:
```
These functions do not control the pipeline dispatcher or command-line parser. The refactor only modifies the orchestration layers (`cli.py`, `engine.py`, and `api.py`) to call these modules sequentially within the new logical stages. The internal audit, scoring, and correction logic remains **completely unchanged**.

### 3.2 Which stages are missing in the current layout?
The current toolkit is missing dedicated, high-level CLI commands and API endpoints for:
1. **`project-scan`**: Currently co-mingled inside `fast` and `full`.
2. **`tech-validate`**: Technical validations (`icu` and `placeholders`) are split into separate ad-hoc scripts rather than a unified gate.
3. **`ar-validate`**: Arabic QC is split across `ar-qc`, `ar-semantic`, and `terminology` instead of a single operational step.
4. **`camel-validate`**: CAMeL cannot be run standalone; it is bound to report generation.

### 3.3 Should CAMeL become an explicit CLI stage?
**Yes.** Elevating CAMeL to an explicit CLI stage (`camel-validate` or `--stage camel-validate`) is highly recommended for three reasons:
1. **Linguistic Isolation**: Allows CI/CD environments and developers to validate Arabic syntax and dialect compliance on translation commits without generating Excel reports.
2. **Automated Gatekeeping**: Pre-checks AI translations using CAMeL POS/spelling metrics prior to human review, raising errors in automated hooks if unknown Arabic tokens exceed thresholds.
3. **Separation of Concerns**: Decouples the heavy NLP libraries (`camel-tools`) from report formatting code, keeping `report_aggregator.py` focused purely on file-generation.

### 3.4 Which existing stages become aliases?
To prevent breaking existing downstream integrations, old stage names will be preserved as transparent wrappers:
* **`fast`**: Alias for executing stages **1, 2 (casing/whitespace only), 3 (except ICU), 4 (if enabled), 5, and 7** in sequence.
* **`full`**: Alias for executing stages **1, 2, 3, 4 (if enabled), 5, and 7** in sequence.
* **`grammar`**: Alias for stage **2**.
* **`terminology`**: Alias for stage **5** (filtering to glossary checks).
* **`placeholders`** and **`icu`**: Aliases for stage **3**.
* **`ar-qc`** and **`ar-semantic`**: Aliases for stage **5**.
* **`reports`**: Alias for stage **7**.
* **`autofix`**: Alias for stage **9 (auto_safe corrections only)**.
* **`ai-review`**: Alias for stage **4**.

### 3.5 Which stages should remain backward compatible?
**All existing CLI stages must remain backward compatible.** Changing command names, options, or argument flags would break CI/CD pipelines and regression suites. The new logical stages will be accessible via *new* stage names (e.g. `--stage technical-validation`), but the old options will be internally re-routed to run their equivalent logical modules.

---

## 4. Affected Files and Impact Analysis

| File Path | Description of Change | Risk Level |
|---|---|---|
| `l10n_audit/core/cli.py` | Add new CLI commands/subparsers for the 9 operational stages. Map old stage flags to the new dispatcher. | **Low** (Parser additive changes only) |
| `l10n_audit/api.py` | Update `run_audit()` parameters to support new operational stages and validate incoming arguments against the new stage set. | **Low** (API validation logic) |
| `l10n_audit/core/engine.py` | Refactor `_dispatch_stage()` to decouple the pipeline into the 9 logical methods. Decouple `camel_decorator` execution from reporting and wire it into its own stage. | **Medium** (Orchestration core) |
| `l10n_audit/reports/report_aggregator.py` | Remove direct invocation of `decorate_with_camel()`. The aggregator will expect to ingest pre-decorated CAMeL metrics from the shared `AuditIssue` cache or cache directories. | **Medium** (Coupling decoupling) |

---

## 5. Migration Risk Level
* **Overall Risk: Low to Medium**
* **Rationale**: We are **not** modifying the core scoring algorithms, database queries, file writing logic, or localization formatting. All existing regression tests (which validate the correctness of individual audits, file writes, and hash gates) will pass cleanly because the refactor only changes *how* the execution loops are scheduled in `engine.py`.

---

## 6. Recommended Implementation Order (Migration Roadmap)

We recommend a 4-step execution plan to ensure zero downtime and 100% test compliance:

### Step 1: Add New Stage Constants and Schema Support
1. Update `VALID_STAGES` in `l10n_audit/models.py` to include the new operational stage names:
   * `project_scan`, `en_validation`, `tech_validation`, `trans_generation`, `ar_validation`, `camel_validation`, `reporting`
2. Ensure the CLI arguments accept these new values.

### Step 2: Refactor Orchestrator Core (`engine.py`)
1. Implement 9 distinct private routing methods in `engine.py` matching the new stages:
   * `_run_project_scan()`, `_run_en_validation()`, `_run_tech_validation()`, etc.
2. Re-route `_dispatch_stage()` so that calling the new stages executes these isolated methods.
3. Map legacy stage names (`fast`, `full`) to call these new methods sequentially in the correct operational order.

### Step 3: Decouple CAMeL Validation
1. Move the execution of `decorate_with_camel` out of `report_aggregator.py` and into the new `_run_camel_validation()` method in `engine.py`.
2. Save CAMeL analysis metrics into the intermediate JSON findings cache (`.cache/raw_tools/`).
3. Update `report_aggregator.py` to load pre-calculated `camel_*` fields from the cache rather than invoking the decorator dynamically.

### Step 4: Validate and Run Regression Suite
1. Run all regression tests to ensure the apply contract validation (`source_hash` check, `plan_id` consistency, `__UNRESOLVED_LOOKUP__` rejection) remains fully intact.
2. Validate that `review_queue.xlsx` continues to emit exactly the correct column layout.
