# L10n Audit Toolkit — Pre-Refactor Architectural Baseline

**Document Class:** Pre-Refactor Architectural Baseline  
**Version Captured:** v1.5.4  
**Baseline Date:** 2026-04-12  
**Status:** FROZEN — for reference only. No implementation prescribed herein.

---

## 1. Executive Baseline Summary

The L10n Audit Toolkit is a multi-stage command-line localization auditing system that ingests locale files (JSON, Laravel PHP, Flutter ARB, etc.), scans source code for key usage, runs a battery of audit modules (grammar, terminology, placeholder, ICU, Arabic QC, AI review), aggregates findings into a unified report, and mediates a three-stage human-review apply workflow (`run` → `prepare-apply` → `apply`).

The current architecture exhibits the following observable characteristics:

- **No single canonical identity** exists for a localization finding from the moment of detection through to apply. Findings travel as raw dicts through normalization layers, acquiring identity fields (`plan_id`, `source_hash`, `key`, `locale`, `issue_type`) only progressively — first loosely in the raw tool JSON, then more formally during `build_review_queue()`, and finally frozen into a hash-validated contract only at `prepare-apply` time.

- **Value / current-state hydration is deferred** to the `report_aggregator.build_review_queue()` call, which is the first point in the pipeline where live locale file data is systematically correlated back to issues. Audit modules emit findings without current values; the aggregator is responsible for looking them up. For Laravel PHP, this lookup involves flattened dot-separated key resolution with suffix-matching semantics.

- **`report_aggregator.py` is an overloaded module.** It owns business logic for: locale inference, value hydration, candidate safety gating, identity deduplication, decision quality classification, review row normalization, human workbook projection, and JSON artifact emission — all co-mingled in a single file of ~1,700 lines.

- **Locale inference is implemented as a permissive multi-fallback chain** across 6 resolution strata (explicit → source-map → key-prefix → file-path → code → details), with no hard enforcement of a single canonical locale field at issue creation time.

- **The apply contract is workbook-driven.** The official execution gate for `apply` is the `review_final.xlsx` file produced by `prepare-apply`. Apply reads rows from this file, validates them against runtime locale data, and rejects any row where the `source_hash` does not match the hash of the current runtime value. This is the primary integrity mechanism.

---

## 2. Confirmed Structural Facts

### 2.1 Identity Fragmentation

**Fact:** There is no single canonical identity object for a localization finding. A finding's identity is assembled incrementally across three layers:

1. **Raw tool layer** (`REPORT_FILE_MAP` JSON files): Issues are plain dicts with inconsistent field presence. The `issue_type` field can be `None`, `""`, or a legacy string. `locale` is optional. Neither `plan_id` nor `source_hash` exists at this stage.

2. **Normalization layer** (`audit_report_utils.py` `NORMALIZERS`): Tool-specific normalizers add `source`, `group`, `severity`, and `details`. The `locale` field is hard-coded per normalizer (e.g., `locale_qc` → `"en"`, `ar_locale_qc` → `"ar"`, `placeholders` → `"en/ar"`). There is no universal `AuditFinding` struct enforced here.

3. **Aggregation layer** (`report_aggregator.build_review_queue()`): This is the first location where `plan_id`, `source_hash`, `suggested_hash`, `old_value`, and `generated_at` are computed and attached. Identity fields are derived from `(key, locale, issue_type)` composites, not from a pre-assigned UUID at detection time.

**Fact:** `AuditIssue` in `models.py` exists as a typed dataclass but is not the primary transport between pipeline stages. The dominant transport is raw `dict`. `AuditIssue` is used primarily at the `api.py` surface boundary.

**Fact:** `issue_from_dict()` in `models.py` conflates `suggestion`, `suggested_fix`, and `approved_new` into the same fields during construction, accepting any of them as aliases. This means the same semantic concept is carried under multiple field names depending on which audit module emitted the issue.

---

### 2.2 Value / Current-State Hydration

**Fact:** Value hydration (resolving the live translation string for a given key) is performed inside `report_aggregator.build_review_queue()` via `_hydrate_old_value_for_issue()`, which calls `resolve_issue_current_value_state()` from `locale_utils.py`.

**Fact:** Audit modules themselves do **not** systematically hydrate `current_value`. Some modules embed it in `details.old` or `target`; others omit it entirely. The aggregator compensates by performing a live locale file lookup at queue-build time.

**Fact:** The hydration path depends on `resolve_issue_locale()` returning a resolvable locale. If locale resolution fails, hydration falls back to `locale_context` (inferred from `issue_type`), and if that also fails, the value is left empty and the `source_hash` is set to the sentinel constant `__UNRESOLVED_LOOKUP__`.

**Fact:** For Laravel PHP projects, locale data is loaded from a directory of `.php` files and flattened to dot-separated keys at load time. The key `messages.auth.failed` flattened from `resources/lang/en/messages.php` means the `old_value` lookup requires matching a fully-qualified canonical key, not the raw key emitted by the audit module. `resolve_canonical_locale_key()` in `locale_utils.py` attempts exact match, then unambiguous suffix match.

**Fact:** `UNRESOLVED_LOOKUP_SOURCE_HASH` (`"__UNRESOLVED_LOOKUP__"`) is a sentinel — not a hash of the empty string. This distinction is explicitly tested and enforced: a row with this sentinel is blocked at apply time by the `source_hash_mismatch` check.

---

### 2.3 Report / Apply Coupling

**Fact:** `report_aggregator.py` contains both the `build_review_queue()` pipeline function (producing review rows) and the complete business logic for: candidate resolution (`_resolve_candidate_value()`), decision quality classification (`_classify_decision_quality()`), brand/identity safety gating (`_is_unsafe_mutation()`), contextual grammar guards, pattern completion vetoes, `approved_new` auto-projection (`_project_approved_new()`), review row normalization (`_normalize_review_row()`), and workflow state application (`apply_workflow_state_to_rows()`). These responsibilities are not separated by module boundary.

**Fact:** `fix_merger.py` contains `prepare_apply_workbook()`, which is the point at which `review_queue.xlsx` rows are validated, filtered to "approved" status only, hash-re-verified, and frozen into `review_final.xlsx`. This function is the boundary between human editing and machine execution.

**Fact:** `apply_review_fixes.run_apply()` reads exclusively from `review_final.xlsx` (resolved by `resolve_review_final_path()`), not from `review_queue.xlsx`. The CLI `apply` command enforces this separation and emits an error message directing users to run `prepare-apply` first if `review_final.xlsx` is absent.

**Fact:** There are two `validate_review_row()` functions in the codebase with different field requirements:
- `fix_merger.validate_review_row()` — used during `export_review_queue()`, requires `key`, `locale`, `issue_type`, `message`, `current_value`, `candidate_value`, `generated_at`.
- `apply_review_fixes._validate_apply_row()` — used during `run_apply()`, additionally requires `approved_new`, `source_hash`, `suggested_hash`, and enforces that `approved_new == candidate_value` as a tamper-detection check.

---

### 2.4 Locale Inference and Fallback Resolution

**Fact:** `locale_utils.resolve_issue_locale()` implements a 6-step fallback chain. Steps 3 (key prefix), 4 (file path), 5 (code/source), and 6 (details context) are inference-only, not evidence-backed locale assignments. The multi-step chain means a finding's locale can be "resolved" from a weak signal such as the string "ar" appearing as the first segment of a dot-separated key.

**Fact:** The `_SOURCE_LOCALE_MAP` in `locale_utils.py` maps audit source names to fixed locales. `"grammar"` → `"en"`, `"ai_review"` → `"ar"`, `"terminology"` → `"ar"`. These mappings are hardcoded and applied globally regardless of project-specific locale configuration. A project with a non-Arabic target locale would receive incorrect locale inference from this map.

**Fact:** `build_review_queue()` applies a secondary locale inference pass after `resolve_issue_locale()` returns `None`, using the `issue_type` string (e.g., `"empty_en"` → `source_locale`, `"missing_in_ar"` → `target_locale`). This is a third inference stratum beyond what `locale_utils.py` provides.

**Fact:** For the `placeholders` and `icu_message_audit` sources, `locale` is hard-coded to `"en/ar"` in their normalizers. This compound value bypasses the locale resolver entirely and is treated as a special case.

---

### 2.5 Review / Apply Contract Structure

**Fact:** The review pipeline produces three structurally distinct artifacts in the current codebase:

| Artifact | File | Role |
|---|---|---|
| `review_queue.xlsx` | `Results/review/review_queue.xlsx` | Human editing workspace |
| `review_machine_queue.json` | `Results/review/review_machine_queue.json` | Machine consumer (AI review stage) |
| `review_projection.json` | `Results/review/review_projection.json` | Analytical projection (read-only) |
| `review_final.xlsx` | `Results/review/review_final.xlsx` | Frozen execution contract for apply |

**Fact:** The `REVIEW_QUEUE_WORKBOOK_COLUMNS` list (13 columns) is the canonical schema for `review_queue.xlsx`. The `REVIEW_PROJECTION_COLUMNS` list (20 columns) includes additional internal metadata (`approved_new`, `context_type`, `context_flags`, `semantic_risk`, `lt_signals`, `review_reason`, `provenance`) that does not appear in the workbook.

**Fact:** `build_human_review_queue()` is the adapter that maps the 20-column projection row to the 13-column workbook row. Column name renaming occurs here: `old_value` → `current_value`, `suggested_fix` → `candidate_value`, `notes` → `review_note`. This renaming is a source of identity drift between the internal pipeline representation and the user-visible artifact.

**Fact:** `REVIEW_FINAL_COLUMNS` is a separate 13-column schema defined in `fix_merger.py`. It matches `REVIEW_QUEUE_WORKBOOK_COLUMNS` in structure but includes `approved_new` as an additional field, making the final workbook the place where `approved_new` first becomes a required column.

---

## 3. Current Invariants

The following behavioral invariants are strongly evidenced by both code and tests.

### 3.1 `review_final.xlsx` is the Exclusive Execution Contract for Apply

`run_apply()` accepts only a path to `review_final.xlsx`. Rows must have `status == "approved"` (unless `--all` flag is set). The CLI `apply` command enforces that `review_final.xlsx` exists before proceeding and directs to `prepare-apply` if absent.

*Evidence:* `apply_review_fixes.py` lines 499, 531–532; `cli.py` lines 358–367; `fix_merger.prepare_apply_workbook()` filtering to `status == "approved"`.

---

### 3.2 Hash-Based Apply Validation is a Non-Negotiable Safety Gate

Before any fix is written to locale files, three hash checks are performed:
1. `source_hash` from the row must equal `compute_text_hash(runtime_current_value)` — confirms the locale file has not changed since the review was generated.
2. `suggested_hash` from the row must equal `compute_text_hash(candidate_value)` — confirms the suggested value column has not been tampered with.
3. `approved_new` must equal `candidate_value` — confirms the approved value matches the original suggestion (tamper detection).

*Evidence:* `apply_review_fixes._validate_apply_row()` lines 191–212, 176–183; `test_apply_review_fixes.py` `test_apply_rejects_source_hash_mismatch`, `test_apply_rejects_tampered_approved_new`.

---

### 3.3 The `__UNRESOLVED_LOOKUP__` Sentinel Must Not Be Treated as Valid

A `source_hash` of `"__UNRESOLVED_LOOKUP__"` means the hydration layer could not resolve a live locale value for the key. Such a row must never be applied. The sentinel is distinct from `compute_text_hash("")` (the hash of a genuinely empty string), and apply validation rejects it via `source_hash_mismatch`.

*Evidence:* `report_aggregator.py` line 71 (`UNRESOLVED_LOOKUP_SOURCE_HASH = "__UNRESOLVED_LOOKUP__"`); `test_apply_review_fixes.py` `test_apply_rejects_unresolved_lookup_source_hash_sentinel`.

---

### 3.4 Laravel PHP Loader Emits Group-Prefixed Flattened Keys

The Laravel PHP locale loader flattens nested PHP array structures to dot-separated keys with the filename as the first segment: `messages.auth.failed` from `messages.php → ['auth' => ['failed' => '...']]`. Raw keys emitted by audit modules may not include the file prefix, requiring suffix-based resolution at hydration time.

*Evidence:* `test_report_aggregator.py` `test_build_review_queue_laravel_resolves_canonical_key_via_locale_context`, `test_build_review_queue_laravel_resolves_unambiguous_suffix_key`; `locale_utils.resolve_canonical_locale_key()` suffix match logic.

---

### 3.5 Info-Severity Issues Are Suppressed from the Review Queue

`build_review_queue()` skips any issue where `severity == "info"`. AI review issues are emitted with `severity = "info"` by `normalize_ai_review()`, meaning AI suggestions enter the review queue only via the `review_machine_queue.json` path, not via the main info-suppression filter.

*Evidence:* `report_aggregator.build_review_queue()` line 767–768; `audit_report_utils.normalize_ai_review()` line 329.

---

### 3.6 The `review_queue.xlsx` Column Schema is a Frozen 13-Column Contract

`REVIEW_QUEUE_WORKBOOK_COLUMNS` defines exactly 13 columns. Changes to this list break the apply pipeline because `prepare_apply_workbook()` reads these columns by name and `_REQUIRED_PREPARE_QUEUE_FIELDS` in `fix_merger.py` validates against them.

*Evidence:* `test_contract_freeze.py` `test_review_final_column_freeze()` (asserts exact column set for `REVIEW_FINAL_COLUMNS`); `test_report_aggregator.py` `test_human_review_queue_workbook_contract_excludes_approved_new()`.

---

### 3.7 `plan_id` is the Stable Primary Identity for Reconciliation

`reconcile_master_from_xlsx()` and `_stable_identity()` both treat `plan_id` as the primary key for matching rows across XLSX and `audit_master.json`. The fallback composite `key|locale|source_hash` is used only when `plan_id` is absent.

*Evidence:* `apply_review_fixes._stable_identity()` lines 334–353; `reconcile_master_from_xlsx()` lines 255–272.

---

### 3.8 Decision Quality Tokens Form a Frozen Vocabulary

The `notes` field of a review queue row may only contain tokens from the set:  
`[DQ:SAFE_AUTO_PROJECTED]`, `[DQ:SUGGESTION_ONLY]`, `[DQ:BLOCKED]`, `[DQ:REVIEW_REQUIRED]`, `[CONFLICT:STRUCTURAL_RISK]`, `[CONFLICT:SAFETY_VETO]`, `[KEEP:CURRENT_VALUE]`, `[NO_CANDIDATE]`, `[DQ:STALE_DECISION]`.

*Evidence:* `test_contract_freeze.py` `test_strict_token_discipline()`.

---

### 3.9 `approved_new` is Excluded from the Human Workbook but Required at Apply Time

`review_queue.xlsx` does not include an `approved_new` column (tested explicitly). The human fills `candidate_value` and sets `status = approved`. `prepare-apply` carries `candidate_value` across to `approved_new` in `review_final.xlsx`. Apply then validates `approved_new == candidate_value`.

*Evidence:* `test_report_aggregator.py` `test_human_review_queue_workbook_contract_excludes_approved_new()`; `fix_merger.build_validated_row()` line 130 (`approved_new = candidate_value`).

---

### 3.10 Apply Is Idempotent Per `suggested_hash` Within a Single Run

`run_apply()` maintains an `applied_suggestions` set keyed on `suggested_hash`. A second row proposing the same `suggested_hash` is rejected as a `duplicate_application`.

*Evidence:* `apply_review_fixes.run_apply()` lines 213–215; `test_apply_review_fixes.py` `test_apply_rejects_duplicate_application`.

---

### 3.11 Stale Rows Are Blocked by Hash Mismatch, Not by Field Absence

A row whose `source_hash` no longer matches the live file value is rejected with `source_hash_mismatch`, regardless of whether all other fields are present and valid. This is the primary defense against stale apply operations.

*Evidence:* `test_apply_review_fixes.py` `test_apply_rejects_stale_row`.

---

## 4. Regression Guard Tests

The following tests serve as architectural guards. They protect invariants that must survive future refactoring phases.

---

### 4.1 `test_apply_rejects_source_hash_mismatch` (`test_apply_review_fixes.py`)

**Behavior protected:** The hash-based apply safety gate. A row whose `source_hash` does not match the current live value must be rejected.  
**Refactor phase relevance:** Any changes to how `source_hash` is computed or stored; any changes to the `_validate_apply_row()` boundary.

---

### 4.2 `test_apply_rejects_unresolved_lookup_source_hash_sentinel` (`test_apply_review_fixes.py`)

**Behavior protected:** The `__UNRESOLVED_LOOKUP__` sentinel is treated as invalid and blocks apply. Unresolved hydration must not propagate silently to execution.  
**Refactor phase relevance:** Any changes to value hydration; any changes to the sentinel constant; any changes to the apply validation path.

---

### 4.3 `test_apply_rejects_tampered_approved_new` (`test_apply_review_fixes.py`)

**Behavior protected:** Tamper detection — `approved_new != candidate_value` is a hard block.  
**Refactor phase relevance:** Any changes to how `approved_new` is populated in `review_final.xlsx` or carried through the apply pipeline.

---

### 4.4 `test_apply_accepts_valid_row` (`test_apply_review_fixes.py`)

**Behavior protected:** The end-to-end apply happy path. A well-formed, hash-consistent, approved row must be applied to the locale file.  
**Refactor phase relevance:** Any changes to the apply pipeline or locale file write path.

---

### 4.5 `test_apply_trace_consistency_with_report_views` (`test_apply_review_fixes.py`)

**Behavior protected:** The apply trace, applied list, and skipped list maintain internal count consistency. `len(trace) == len(applied) + len(skipped)`.  
**Refactor phase relevance:** Any refactoring of the apply loop or trace recording logic.

---

### 4.6 `test_exact_20_column_freeze` (`test_contract_freeze.py`)

**Behavior protected:** The `REVIEW_QUEUE_COLUMNS` projection internal schema is exactly 20 columns. Any addition or removal breaks downstream analytics.  
**Refactor phase relevance:** Any changes to the review row schema or `build_review_queue()` output structure.

---

### 4.7 `test_review_final_column_freeze` (`test_contract_freeze.py`)

**Behavior protected:** `REVIEW_FINAL_COLUMNS` in `fix_merger.py` is exactly the 13-column frozen schema. Mutation breaks the apply pipeline.  
**Refactor phase relevance:** Any changes to `prepare_apply_workbook()` output, `fix_merger.py` schema definitions, or apply workbook reading.

---

### 4.8 `test_strict_token_discipline` (`test_contract_freeze.py`)

**Behavior protected:** Decision quality tokens in the `notes` field are from a frozen vocabulary. Unknown tokens must not appear.  
**Refactor phase relevance:** Any changes to `_classify_decision_quality()` or `_normalize_review_row()`.

---

### 4.9 `test_build_review_queue_failed_lookup_uses_unresolved_hash_sentinel` (`test_report_aggregator.py`)

**Behavior protected:** A failed key lookup must produce the `__UNRESOLVED_LOOKUP__` sentinel, not an empty-string hash.  
**Refactor phase relevance:** Any changes to `_hydrate_old_value_for_issue()`, `resolve_canonical_locale_key()`, or the sentinel constant.

---

### 4.10 `test_build_review_queue_true_empty_translation_keeps_empty_hash` (`test_report_aggregator.py`)

**Behavior protected:** A key that exists in the locale file with an empty string value must produce `compute_text_hash("")` as `source_hash`, not the unresolved sentinel. The two cases must be distinguishable.  
**Refactor phase relevance:** Any changes to hydration logic or sentinel handling.

---

### 4.11 `test_build_review_queue_laravel_resolves_canonical_key_via_locale_context` (`test_report_aggregator.py`)

**Behavior protected:** Laravel PHP group-prefixed key `messages.auth.failed` must resolve correctly to the English locale value when the issue's locale context is `"en"`.  
**Refactor phase relevance:** Any changes to the Laravel PHP loader, the key resolution chain, or how `locale_context` is derived for Laravel issues.

---

### 4.12 `test_phase12_full_cycle_apply_closure` (`test_apply_cycle_closure.py`)

**Behavior protected:** After an issue is applied, a re-run that finds the same key with the updated value produces zero actionable review rows. The pipeline does not reopen resolved issues.  
**Refactor phase relevance:** Any changes to the deduplication logic in `build_review_queue()`, or the `apply_workflow_state_to_rows()` function.

---

### 4.13 `test_phase12_stale_rerun_proof` (`test_apply_cycle_closure.py`)

**Behavior protected:** When a row matches a previously-applied `plan_id` but the `source_hash` has shifted (content changed after apply), the row is marked `stale` rather than silently re-applying the old decision.  
**Refactor phase relevance:** Any changes to `apply_workflow_state_to_rows()` or the stale-detection logic.

---

### 4.14 `test_run_stage_emits_review_queue_xlsx_not_review_projection_xlsx` (`test_report_aggregator.py`)

**Behavior protected:** `run_stage()` emits `review_queue.xlsx` as the primary human artifact. `review_projection.xlsx` must not be emitted.  
**Refactor phase relevance:** Any changes to the artifact emission section of `report_aggregator.run_stage()`.

---

### 4.15 `test_registry_semantic_roles_are_explicit` (`test_patch_9_json_role_separation.py`)

**Behavior protected:** The artifact registry maintains distinct, named roles: `human_apply_contract`, `machine_consumer_queue`, `analytical_projection`, `compatibility_alias`. These roles must not collapse.  
**Refactor phase relevance:** Any changes to `artifact_resolver.py`, `deprecation_registry.py`, or artifact path resolution logic.

---

## 5. Open Architectural Debt

### 5.1 `report_aggregator.py` Violates the Single Responsibility Principle

At ~1,700 lines, the report aggregator owns: locale inference, value hydration, candidate safety gating, identity deduplication, decision quality classification, review row normalization, human workbook projection, JSON artifact emission, workflow state application, and markdown report generation. These are seven or more distinct responsibilities that cannot be independently tested or replaced without coupling to the full aggregator.

---

### 5.2 No Canonical Finding Identity at Detection Time

Findings enter the pipeline as raw dicts without a pre-assigned stable identity. `plan_id` is a hash derived from `(key, locale, issue_type, candidate_value)` and is only computed inside `build_review_queue()`. This means there is no stable identity reference across pipeline runs unless the `plan_id` generation inputs remain identical — which they will not if the candidate value changes, the issue type evolves, or locale inference produces a different result.

---

### 5.3 Internal Locale Inference Is Permissive and Side-Effect-Prone

The 6-step fallback in `resolve_issue_locale()` means that a finding with only a source name (`"grammar"`) and no explicit locale field will receive `"en"` from the source map. This is correct for the current set of sources but is a soft invariant: adding a new audit source without updating `_SOURCE_LOCALE_MAP` will silently produce `None`, causing the secondary inference in `build_review_queue()` to take over — or worse, causing the issue to be emitted with `locale = "unknown"`.

---

### 5.4 The `old_value` / `current_value` Field Name Collision

Internally, the pipeline uses `old_value` for the current translation (the value before any fix). The human workbook uses `current_value` for the same concept. The `source_old_value` column in the workbook is a copy of `old_value` preserved for hash verification. This three-name collision for a single semantic concept (`the value at review time`) creates confusion in the apply validation path where both `current_value` (workbook column) and `source_old_value` must agree.

*Evidence:* `fix_merger._validate_prepare_apply_row()` line 341: `if normalized["source_old_value"] != normalized["current_value"]`.

---

### 5.5 `AuditIssue` in `models.py` Is Not the Primary Transport

The typed `AuditIssue` dataclass exists at the API boundary but raw `dict` is the dominant in-pipeline transport. This means the type system does not enforce field presence, defaults, or invariants during the critical normalization and aggregation phases. Type errors surface at runtime, not at development time.

---

### 5.6 `issue_from_dict()` Aliases Multiple Competing Fields

`models.py` `issue_from_dict()` accepts `suggestion`, `suggested_fix`, or `approved_new` interchangeably and maps them all to both `suggestion` and `suggested_fix` on the resulting `AuditIssue`. This aliasing collapses a semantic distinction: `suggestion` (AI/LT output before review) vs. `approved_new` (human-confirmed post-review). At the API surface, these have lost their provenance.

---

### 5.7 `_SOURCE_LOCALE_MAP` Hardcodes a Two-Locale Assumption

The map assumes `en` and `ar` as the only possible locales. A project with a different language pair (e.g., `en`/`fr`) would receive incorrect locale assignments from the source-based inference stratum, particularly for `"ai_review"` → `"ar"` and `"terminology"` → `"ar"`.

---

### 5.8 `validate_review_row()` in `fix_merger.py` Requires `message` But Apply Does Not

The `export_review_queue()` validation path requires a non-empty `message` field. The apply path does not. This inconsistency means a finding without a human-readable message would be rejected at queue export time but would have been accepted by the apply validator if it somehow reached `review_final.xlsx`.

---

### 5.9 Apply Writes Two Separate Locale Fix Outputs With No Consistency Check

`run_apply()` writes `auto_fixes_en`, `auto_fixes_ar`, `review_fixes_en`, and `review_fixes_ar` as four separate mappings, merges them independently, and calls `merge_and_export_fixes()` once for EN and once for AR. There is no cross-locale consistency check — a row approved for `ar` that conflicts with a fix in `en` is not detected.

---

### 5.10 `build_review_queue()` Deduplicates by `(key, locale)` Pair Only

When two issues share the same `(key, locale)` pair (e.g., from `locale_qc` and `grammar`), the second issue updates the existing row via `_is_merge_compatible_review_issue()`. This merge logic is complex and preserves the first row's `plan_id` while potentially updating the suggestion from the second. The resulting row's provenance then reflects both sources, but its `plan_id` was generated from the first issue's content — creating a silent identity dependency on arrival order.

---

## 6. Refactor Safety Notes

The following constraints must be respected during future refactoring phases to prevent silent regressions.

### 6.1 The `__UNRESOLVED_LOOKUP__` Sentinel Must Remain Distinct from `compute_text_hash("")`

Any refactoring of the hydration layer must preserve the behavioral distinction between a failed lookup (`source_hash = "__UNRESOLVED_LOOKUP__"`) and a resolved-but-empty translation (`source_hash = compute_text_hash("")`). These cases are handled differently downstream and are protected by dedicated tests.

---

### 6.2 The Apply Hash Validation Chain Must Remain Intact

Any canonical-core unification that introduces a new identity model must preserve (or replace with an equivalent) the three-part hash validation in `_validate_apply_row()`: source hash verification, suggested hash verification, and tamper detection (`approved_new == candidate_value`). These checks are the primary execution safety mechanism.

---

### 6.3 The Human Workbook Schema Must Not Silently Diverge from the Apply Validator's Expectations

`REVIEW_QUEUE_WORKBOOK_COLUMNS` (what `build_human_review_queue()` emits), `_REQUIRED_PREPARE_QUEUE_FIELDS` (what `prepare_apply_workbook()` reads), and `REQUIRED_REVIEW_COLUMNS` (what `run_apply()` reads) are three distinct constant lists that must remain mutually consistent. Any refactoring that changes one must update all three and their associated tests.

---

### 6.4 `plan_id` Generation Must Remain Deterministic Per Issue State

`plan_id` is computed via `compute_plan_id(key, locale, issue_type, candidate_value)` (or similar). If the inputs change across runs for the same finding, the `plan_id` will differ, breaking `reconcile_master_from_xlsx()` and `_stable_identity()`. Any refactoring that changes `plan_id` generation must ensure that the new scheme is either equally deterministic or migrates the historical `audit_master.json` `workflow_state` entries.

---

### 6.5 The Three-Stage CLI Contract Must Be Preserved

The `run` → `prepare-apply` → `apply` sequence is surfaced in the CLI help text and enforced at runtime (apply aborts if `review_final.xlsx` is absent). Any refactoring of artifact paths or stage coupling must preserve this user-facing contract, or explicitly document and test a changed sequence.

---

### 6.6 Info-Severity Suppression Must Remain a Pipeline Gate

The `severity == "info"` suppression in `build_review_queue()` prevents AI review issues (emitted as `info`) from entering the human workbook through the standard path. Any refactoring of severity handling must preserve this gate, as removing it would flood the workbook with AI suggestions that were previously filtered to the machine-only JSON path.

---

### 6.7 Laravel PHP Suffix Resolution Must Remain Conservative

`resolve_canonical_locale_key()` returns `ambiguous_suffix` when more than one canonical key matches a suffix. This prevents incorrect value binding when multiple locale groups contain keys with the same suffix. Any refactoring of locale key lookup must preserve the unambiguous-match-only guarantee and must not silently coerce ambiguous matches to the first result.

---

### 6.8 The `review_queue.xlsx` / `review_projection.xlsx` Role Separation Must Not Collapse

`review_queue.xlsx` is the human-edit contract. `review_projection.xlsx` is a deprecated analytical artifact. The deprecation registry classifies `review_projection_xlsx` as `deprecated_candidate` with `removal_readiness = "remove_now"`. Any refactoring must not reintroduce `review_projection.xlsx` as a apply-path artifact.

---

### 6.9 The `notes` Token Vocabulary Must Not Be Extended Without Test Coverage

Decision quality tokens in the `notes` field are validated by `test_strict_token_discipline()`. Any new token introduced during refactoring must be added to the token vocabulary list in that test, as undocumented tokens would represent an uncontrolled schema extension.

---

### 6.10 `audit_master.json` Reconciliation Is Additive Only

`reconcile_master()` writes only to the `workflow_state` key and never modifies `issue_inventory`, `review_projection`, or `legacy_artifacts`. This additive-only constraint is architecturally intentional and must not be violated during refactoring. Mutating non-`workflow_state` keys from the apply path would create uncontrolled coupling between the apply stage and the audit phase artifacts.

---

*End of Pre-Refactor Architectural Baseline*
