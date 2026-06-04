# Walkthrough — Phase 1 Decision Safety Patches

We have successfully implemented the first scoped Decision Safety Patch Phase to improve the precision of translation quality decisions and eliminate silent false passes in the L10n Audit Toolkit.

## Changes Made

### 1. Short Ambiguous Strings Routed to Review
* **Target File:** [ai_review.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py)
* **Exact Change:** When `should_invoke_ai` detereministically skips a short ambiguous string that lacks context (`SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT`), instead of silently dropping the finding, the loop now appends it to the list of fixes as a `review_required` finding with `verified=False`, `needs_review=True`, and an empty candidate suggestion.
* **Early Return Handling:** Modified the early-return check `if not batch_items:` to process and return any appended safety findings (e.g. short ambiguous strings) in `all_fixes` even when no batches were sent to the AI provider.

### 2. Identical AI Suggestions Preserved as Uncertainty Findings
* **Target File:** [verification.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py)
* **Exact Change:** Modified the basic structural verification gate where `suggestion.strip() == target_text.strip()` was previously skipped. Instead of silently dropping the candidate, it now appends a custom `review_required` uncertainty finding (`verified=False`, `needs_review=True`, `semantic_reason_codes=["ai_returned_same_text"]`) that preserves the original issue context message so it correctly routes to the human review queue.

### 3. Candidate-less Findings Kept Visible in Review Queue
* **Target Files:** [apply_safe_fixes.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/apply_safe_fixes.py) and [fix_merger.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/fix_merger.py)
* **Exact Changes:**
  * In `apply_safe_fixes.py`: Updated `build_fix_plan` to allow `candidate is None` (representing a finding without a proposed candidate value) by mapping it to `candidate = ""` instead of adding it to `missing_fields` and rejecting the plan item.
  * In `apply_safe_fixes.py`: Updated `classify_issue` to always classify any plan items that have a missing or empty candidate value as `review_required`.
  * In `apply_safe_fixes.py`: Updated the strict security check for AI suggestions to only apply when a candidate value is present, ensuring that candidate-less AI suggestions can pass into the fix plan safely.
  * In `apply_safe_fixes.py`: Preserved `generated_at` when constructing plan items so that they satisfy review queue validation downstream.
  * In `fix_merger.py`: Updated `validate_review_row` and `build_validated_row` to allow empty string values `""` for `candidate_value` and `approved_new` in the review queue so they are not rejected by the string check.

---

## Verification Results

### Automated Tests Added
A new dedicated test file [test_decision_safety_patches.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/tests/test_decision_safety_patches.py) has been added to verify all three scoped changes under isolated and simulated conditions:
1. `test_short_ambiguous_no_context_produces_review_finding`: Proves that skipped short labels do not silently pass and are correctly routed to review.
2. `test_ai_same_text_produces_review_finding`: Proves that identical AI suggestions are caught and kept as review-required uncertainty findings.
3. `test_empty_candidate_plan_and_review_queue`: Proves that findings without a candidate successfully pass through `build_fix_plan` and are exported to the review queue without any validation rejections.

### Tests Run & Results
* **Patches Test Suite:** `pytest tests/test_decision_safety_patches.py` -> **Passed** (3/3 tests)
* **AI Review & Observability Suite:** `pytest tests/test_ai_review_fixes.py tests/test_ai_review_activity_indicator.py tests/test_ai_invocation_and_contract.py tests/test_ai_optimization.py tests/test_phase8_ai_review_alignment.py tests/test_phase9_observability.py` -> **Passed** (80/80 tests)
* **Fix Plan & Review Row Validation Suite:** `pytest tests/test_safe_fixes.py tests/test_review_row_validation.py` -> **Passed** (44/44 tests)
* **Report Aggregator Suite:** `pytest tests/test_report_aggregator.py tests/test_report_candidate_projection.py tests/test_step7_aggregator_main.py` -> **Passed** (87/87 tests)
* **Full Test Suite:** `pytest` -> **Passed** (1,605/1,605 tests successfully passed)
