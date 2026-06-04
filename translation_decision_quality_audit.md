# TRANSLATION DECISION QUALITY AUDIT

## 1. Executive Verdict

**Decision Quality: WEAK — with pockets of strong design**

The toolkit demonstrates sophisticated engineering in several areas (semantic acceptance gate, glossary enforcement, placeholder verification, domain confusion sets). However, the overall decision quality is **weak** because of systemic issues:

1. **The "no issue found" ≡ "correct" conflation**: The system is architectured as an issue-finder, not a correctness-verifier. Translations that pass all detectors are implicitly treated as correct, but the detectors only cover specific failure modes. A grammatically correct, placeholder-preserving, glossary-compliant Arabic translation that is **semantically wrong** (wrong meaning, wrong UI intent, wrong role) will pass silently if no detector fires.

2. **The Decision Engine only routes findings — it never evaluates translations directly**: The confidence scoring in [decision_engine.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/decision_engine.py) operates on **findings** (already-detected issues), not on translations. If no issue is detected, no finding exists, and no routing decision is made. The translation passes by default.

3. **Shadow mode defaults**: The Decision Engine defaults to `respect_routing=False` ([L29](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/decision_engine.py#L29)), Calibration Engine defaults to `enabled=False` ([L171](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L171)), and CalibrationEngine defaults to `shadow` mode ([L325](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L325)). Unless explicitly configured, the entire routing/calibration infrastructure is **inert**.

4. **Candidate quality is inconsistent**: The semantic QC generates candidates by naive verb-prepending (`"أضف " + ar_text`), while the AI review depends entirely on LLM output quality with verification that focuses on structural safety (placeholders, HTML, newlines) rather than semantic correctness.

5. **The short-ambiguous skip in AI review is a false-pass vector**: Short strings (≤4 words) without context or glossary are skipped from AI review entirely ([L360-361](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L360-L361)), but these are exactly the strings most prone to semantic ambiguity.

---

## 2. Top Decision Failures

### F1 — "No finding" treated as "correct translation"
| Attribute | Value |
|---|---|
| **Affected Module** | System-wide architecture |
| **False Pass Risk** | **CRITICAL** |
| **False Review Risk** | None |
| **Candidate Quality Risk** | N/A |
| **Evidence** | No stage performs positive verification of translation correctness. The system only looks for defects. Absence of defect ≠ presence of quality. A literal but grammatically correct Arabic translation that sounds robotic will pass all detectors. |
| **Severity** | Critical |

### F2 — Short-ambiguous strings skipped from AI review
| Attribute | Value |
|---|---|
| **Affected Module** | [ai_review.py:should_invoke_ai()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L307-L363) |
| **False Pass Risk** | **HIGH** |
| **False Review Risk** | None |
| **Candidate Quality Risk** | N/A — no candidate generated |
| **Evidence** | L360: `if _word_count(source_text) <= short_ambiguous_threshold and not glossary and not has_context: return False, SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT`. Short UI labels like "Cancel", "Saved", "Medium" are exactly the ones where Arabic can have domain-wrong translations (شطب vs إلغاء, أنقذ vs تم الحفظ). These are skipped before AI can evaluate them. |
| **Severity** | High |

### F3 — Auto-safe classification without semantic verification
| Attribute | Value |
|---|---|
| **Affected Module** | [apply_safe_fixes.py:classify_issue()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/apply_safe_fixes.py#L75-L112) |
| **False Pass Risk** | **HIGH** |
| **False Review Risk** | None |
| **Candidate Quality Risk** | High — auto-applied without human review |
| **Evidence** | L102-107: AI suggestions are classified as `auto_safe` if `verified=True` AND `is_small_safe_change(old, new)`. The `verified` flag comes from structural verification (placeholders, HTML, newlines) + semantic gate, but `is_small_safe_change` only checks length difference (`abs(len(old) - len(new)) <= max(10, len(old) // 2)` and `<=12 words`). A semantically wrong translation that happens to be similar in length passes. |
| **Severity** | High |

### F4 — AI prompt does not distinguish between "correct" and "no issue"
| Attribute | Value |
|---|---|
| **Affected Module** | [prompts.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/prompts.py) |
| **False Pass Risk** | **HIGH** |
| **False Review Risk** | Medium |
| **Candidate Quality Risk** | High |
| **Evidence** | The prompt asks the AI to "review translation payloads and produce corrections." It returns a single `translated_text` field. There is no explicit "is this translation correct?" verdict. There is no "confidence" field. There is no "I cannot determine" option. The AI must always return a translation, even if the current one is fine, leading to either (a) returning the same text (treated as no-op → suppressed) or (b) making unnecessary changes. |
| **Severity** | High |

### F5 — Semantic QC only detects pattern-based issues, not meaning
| Attribute | Value |
|---|---|
| **Affected Module** | [ar_semantic_qc.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_semantic_qc.py) |
| **False Pass Risk** | **HIGH** |
| **False Review Risk** | Medium |
| **Candidate Quality Risk** | N/A |
| **Evidence** | `detect_semantic_findings()` only checks for: (1) sentence shape mismatch, (2) message-label mismatch, (3) missing action verbs, (4) context-sensitive terms. It does **not** check if the Arabic text means the same thing as the English text. A translation like "Settings" → "إعدادات الطقس" (weather settings) passes because it has the right shape, contains no missing actions, and fires no pattern. |
| **Severity** | High |

### F6 — Decision Engine routing is annotation-only for Arabic
| Attribute | Value |
|---|---|
| **Affected Module** | [decision_engine.py:apply_arabic_decision_routing()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/decision_engine.py#L723-L799) |
| **False Pass Risk** | **MEDIUM** |
| **False Review Risk** | None |
| **Candidate Quality Risk** | None |
| **Evidence** | L779 comment: "Arabic is annotation-only: context fields are attached but route is determined purely by scoring/calibration — no context rule override." The entire decision engine for Arabic rows only injects metadata; it does not enforce routing. Even when a finding gets `route: manual_review`, the downstream pipeline may not honor it. |
| **Severity** | Medium |

### F7 — Candidate == current value suppression hides real issues
| Attribute | Value |
|---|---|
| **Affected Module** | [verification.py:verify_batch_fixes()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L706-L707) |
| **False Pass Risk** | **MEDIUM** |
| **False Review Risk** | None |
| **Candidate Quality Risk** | High |
| **Evidence** | L706-707: `if suggestion.strip() == target_text.strip(): continue`. If the AI returns the same text as the current translation, the issue is silently dropped. But the original issue still exists — the translation might still be wrong. The AI just couldn't think of a better alternative, or thinks the current translation is fine. Both cases are silently suppressed. |
| **Severity** | Medium |

### F8 — Confidence score starts at 0.5 with no evidence
| Attribute | Value |
|---|---|
| **Affected Module** | [decision_engine.py:score_finding()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/decision_engine.py#L565-L591) |
| **False Pass Risk** | **MEDIUM** |
| **False Review Risk** | Low |
| **Candidate Quality Risk** | N/A |
| **Evidence** | L569-577: `base_confidence = 0.5`. A finding with no evidence (no semantic risk, no placeholder issue, no glossary signal) gets confidence 0.5. With `is_simple_fix=True`, a grammar finding adds +0.3 (simple_fix_bonus) + 0.2 (grammar_signal) = 1.0, which routes to `auto_fix` despite having zero semantic verification. |
| **Severity** | Medium |

### F9 — Glossary fuzzy matching is overly permissive
| Attribute | Value |
|---|---|
| **Affected Module** | [verification.py:is_arabic_fuzzy_match()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L568-L595) |
| **False Pass Risk** | **MEDIUM** |
| **False Review Risk** | Low |
| **Candidate Quality Risk** | Medium |
| **Evidence** | L576-594: The function strips Arabic prefixes (ال, ل, ب, ك, و, ف) and removes weak letters (ا, و, ي, ي, ة) for "root-ish" comparison with a tolerance of ±3 characters. This can cause false positives (matching unrelated words that share consonants) and false negatives (missing legitimate glossary violations when the morphological variant is >3 chars different). |
| **Severity** | Medium |

### F10 — AR locale QC over-flags stylistic preferences
| Attribute | Value |
|---|---|
| **Affected Module** | [ar_locale_qc.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_locale_qc.py) |
| **False Pass Risk** | Low |
| **False Review Risk** | **HIGH** |
| **Candidate Quality Risk** | Low |
| **Evidence** | Arabic locale QC has extensive pattern-based rules for spacing, punctuation, exclamation marks, and style. Valid Arabic UI text that uses acceptable stylistic variation (e.g., different comma styles, acceptable briefness) is likely to be flagged for review. The 40+ explicit checks create high noise for correct translations. |
| **Severity** | Medium |

---

## 3. Detector-by-Detector Analysis

### 3.1 AI Review ([audits/ai_review.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py), [ai/verification.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | LLM-powered semantic review of flagged translations |
| **Good at** | Generating alternative translations; structural verification (placeholders, HTML, newlines, glossary) |
| **Cannot prove** | That a translation is semantically correct; that the AI's suggestion is better than the current translation; that the absence of an AI suggestion means the current text is fine |
| **False pass risks** | (1) Short strings skipped entirely via `should_invoke_ai()`. (2) AI returns same text → silently dropped. (3) AI returns "accept" semantic gate → `verified=True` → auto-applied without human oversight. (4) Prompt doesn't ask for correctness verdict. |
| **False review risks** | (1) Semantic gate is conservative — "suspicious" status routes to review even for stylistic differences. (2) Concept coverage check flags valid Arabic brevity as `semantic_key_concept_loss`. |
| **Candidate risks** | (1) AI generates literal translations the prompt says to avoid but cannot always prevent. (2) AI has no product-domain context beyond what the prompt provides. (3) Glossary enforcement retries same prompt up to 5 times but AI may never comply. |
| **Recommended calibration** | Remove the short-ambiguous skip or route those strings to review instead of silently passing. Add an explicit "correctness verdict" to the AI prompt. Treat AI returning same text as "uncertain" not "no issue". |

### 3.2 AR Locale QC ([audits/ar_locale_qc.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_locale_qc.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Pattern-based Arabic text quality checks (spacing, punctuation, style, brevity) |
| **Good at** | Catching whitespace issues, English punctuation in Arabic text, bracket/slash spacing, similar phrase variation |
| **Cannot prove** | Semantic correctness; meaning preservation; appropriate UI tone |
| **False pass risks** | (1) Only checks surface patterns — semantically wrong text that is well-formatted passes. (2) No meaning comparison to English source. |
| **False review risks** | (1) High volume of stylistic findings (exclamation spacing, long string warnings). (2) Similar phrase variation can flag acceptable Arabic synonyms. (3) Suspicious literal translation detector may flag valid short Arabic UI labels. |
| **Candidate risks** | Candidates are mechanical transformations (add space, swap punctuation character) — low risk but low value for semantic issues. |
| **Recommended calibration** | Reduce severity of pure-style findings from "medium" to "info". Add a suppression rule for known-acceptable Arabic stylistic variants. |

### 3.3 AR Semantic QC ([audits/ar_semantic_qc.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_semantic_qc.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Detect semantic mismatches between English source and Arabic translation |
| **Good at** | Detecting sentence-shape mismatches (sentence-like EN → short-label AR); detecting missing action verbs |
| **Cannot prove** | That a translation preserves meaning. Only checks structural shape and verb presence. Does not compare semantics. |
| **False pass risks** | **(Critical)** (1) Can only detect 7 action verbs (save, add, send, select, enter, approve, delete). Any other verb mismatch is invisible. (2) No noun/entity matching. (3) No polarity detection. (4) No tense verification. (5) Arabic text that is grammatical but means something completely different passes. |
| **False review risks** | (1) `sentence_shape_mismatch` fires when valid Arabic brevity correctly condenses an English sentence. (2) `possible_meaning_loss` fires for short labels where the missing action is implicit in Arabic UI context. |
| **Candidate risks** | **(High)** Candidates are generated by `build_semantic_candidate()` which simply prepends an Arabic imperative verb: `"أضف " + ar_text`. This is naive — it doesn't account for Arabic sentence structure, agreement, or whether the prepended verb even makes sense in context. Multi-action strings are correctly suppressed (L103-104), as are status strings (L115-116), but single-action candidates can still be structurally absurd. |
| **Recommended calibration** | Don't generate candidates for semantic issues unless context strongly supports the specific verb. Route semantic findings to review rather than producing mechanical candidates. Consider marking semantic shape mismatches as "info" when the Arabic word count is >1 (likely intentional brevity, not loss). |

### 3.4 LanguageTool ([core/languagetool_layer.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/languagetool_layer.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Grammar/style checking via LanguageTool integration |
| **Good at** | Catching English grammar errors; providing well-formed suggestions |
| **Cannot prove** | That Arabic text is semantically correct (LanguageTool's Arabic support is limited). Arabic grammar findings are best-effort shadow signals. |
| **False pass risks** | (1) LanguageTool's Arabic module has limited rule coverage. (2) Signals are merged into context but may not escalate findings on their own. |
| **False review risks** | (1) English grammar rules may fire on technical text or intentional informal UI tone. (2) Style rules can flag acceptable UI phrasing. |
| **Candidate risks** | LanguageTool suggestions are grammar-focused — generally high quality for what they cover but do not address semantic issues. |
| **Recommended calibration** | Use LanguageTool signals as additive evidence in the decision engine but never as sole evidence for auto-fix. Current integration appears to do this correctly via the `grammar_signal` bonus in scoring. |

### 3.5 CAMeL/Arabic NLP Layer ([ai/arabic_nlp_layer.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/arabic_nlp_layer.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Shadow-mode Arabic NLP signals (morphological analysis, diacritization) |
| **Good at** | Providing Arabic-specific linguistic metadata |
| **Cannot prove** | Translation correctness — signals are informational only |
| **False pass risks** | CAMeL signals are shadow-mode only; they do not directly influence routing decisions. This means valuable morphological information that could catch errors is not used for decision-making. |
| **False review risks** | None — signals are not used for routing |
| **Candidate risks** | N/A |
| **Recommended calibration** | Consider promoting specific CAMeL signals (e.g., morphological disagreement between source action and target form) from shadow to soft evidence in the decision engine scoring. |

### 3.6 Terminology Audit ([audits/terminology_audit.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/terminology_audit.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Enforce glossary term usage in translations |
| **Good at** | Detecting forbidden terms; verifying approved term presence |
| **Cannot prove** | Overall translation quality — only checks specific glossary entries |
| **False pass risks** | (1) Glossary coverage is project-dependent — ungoverned terms can drift. (2) Arabic morphological variants may not match exact glossary entries. |
| **False review risks** | (1) Fuzzy matching may catch morphological variants that are actually correct. (2) Terms that appear in source but are correctly handled implicitly in Arabic may still be flagged. |
| **Candidate risks** | Terminology suggestions are glossary-driven and generally high quality. |
| **Recommended calibration** | Tighten the `is_arabic_fuzzy_match()` function to reduce false positives from consonant-skeleton matching. |

### 3.7 Placeholder Audit ([audits/placeholder_audit.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/placeholder_audit.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Verify placeholders are preserved in translations |
| **Good at** | Catching missing, extra, or damaged placeholders |
| **Cannot prove** | Semantic correctness — only checks placeholder integrity |
| **False pass risks** | Low — placeholder checking is structural and reliable |
| **False review risks** | (1) Arabic text containing placeholder-like patterns (e.g., `{word}` that is actually Arabic content) may false-fire. (2) Reordered placeholders are valid in Arabic (different word order) but may be flagged as mismatches depending on the check logic. |
| **Candidate risks** | Placeholder corrections are mechanical and safe. |
| **Recommended calibration** | No major changes needed — this is one of the most reliable detectors. |

### 3.8 ICU Audit ([audits/icu_message_audit.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/icu_message_audit.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Validate ICU message format syntax |
| **Good at** | Catching ICU syntax errors, mismatched braces, invalid plural rules |
| **Cannot prove** | That the ICU message semantically matches the source intent |
| **False pass risks** | Low — ICU syntax validation is deterministic |
| **False review risks** | Arabic ICU plural rules are complex (6 forms vs English 2); valid Arabic pluralization may be flagged if the tool expects strict form matching. |
| **Candidate risks** | Low — ICU fixes are structural |
| **Recommended calibration** | Ensure Arabic plural form count (zero, one, two, few, many, other) is correctly recognized as valid. |

### 3.9 Decision Engine ([core/decision_engine.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/decision_engine.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Score findings and route to auto_fix/ai_review/manual_review/dropped |
| **Good at** | Deterministic, multi-signal scoring with evidence tracking; feedback-aware calibration |
| **Cannot prove** | Translation correctness — only operates on existing findings. If no finding exists, no decision is made. |
| **False pass risks** | **(Critical)** (1) Only evaluates detected findings — non-findings are invisible. (2) `base_confidence = 0.5` with additive bonuses can reach 0.8 (auto_fix threshold) with just `simple_fix_bonus(+0.3)` + `grammar_signal(+0.2)` = 1.0, requiring zero semantic evidence. |
| **False review risks** | (1) Missing suggestion penalty (-0.4) is severe — a finding without a candidate suggestion drops to 0.1, forcing manual_review even for simple grammar issues. (2) Multiple penalty stacking can over-penalize routine findings. |
| **Candidate risks** | Decision engine does not generate candidates — only routes findings. |
| **Recommended calibration** | (1) Require at least one semantic evidence signal before allowing auto_fix. (2) Reduce the missing_suggestion_penalty or make it conditional on issue type. (3) Ensure the `is_simple_fix` flag is set based on actual evidence, not just the issue source. |

### 3.10 Review Queue Suppression ([fixes/apply_safe_fixes.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/apply_safe_fixes.py), [fixes/fix_merger.py](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/fix_merger.py))

| Aspect | Assessment |
|---|---|
| **Purpose** | Build fix plans and export review queues |
| **Good at** | Deduplication; conflict resolution; integrity verification |
| **Cannot prove** | That suppressed/deduplicated items didn't hide real issues |
| **False pass risks** | (1) `candidate == current_value` check silently suppresses rows. (2) Deduplication by signature may merge distinct issues. (3) Missing `candidate_value` causes fix plan rejection — the issue disappears from the pipeline. |
| **False review risks** | (1) Conflicting candidates for same key escalate to review even if one candidate is clearly correct. |
| **Candidate risks** | (1) Candidates from multiple sources (AI, terminology, semantic QC) may contradict each other. (2) Fix merger uses priority ordering (staged > auto_fix > AI), which may suppress a better candidate from a lower-priority source. |
| **Recommended calibration** | (1) When candidate == current value, don't suppress the finding — route it to review with a flag indicating the tool couldn't find a better alternative. (2) Log suppressed/deduplicated items for audit trail. |

---

## 4. Suppression and No-op Risk Audit

### S1 — AI verification: suggestion == target suppression
| Attribute | Value |
|---|---|
| **Location** | [verification.py:L706-707](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L706-L707) |
| **Why it exists** | Prevents applying a "fix" that changes nothing |
| **What valid issue it may hide** | The original issue that triggered AI review still exists. The AI couldn't fix it, but the translation is still wrong. The issue disappears from all downstream processing. |
| **Required test** | Feed a known-bad translation where AI returns the same text. Verify the original issue survives in the review queue. |

### S2 — should_invoke_ai: short-ambiguous skip
| Attribute | Value |
|---|---|
| **Location** | [ai_review.py:L360-361](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L360-L361) |
| **Why it exists** | Avoids wasting AI tokens on strings too short to provide context |
| **What valid issue it may hide** | Short UI labels with domain-wrong translations (e.g., "Cancel" → "شطب" instead of "إلغاء"). These are exactly the translations most likely to be wrong. |
| **Required test** | Feed known-wrong short translations. Verify they are not silently passed. |

### S3 — should_invoke_ai: auto_safe classification skip
| Attribute | Value |
|---|---|
| **Location** | [ai_review.py:L344-345](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L344-L345) |
| **Why it exists** | Avoids re-reviewing strings already classified as safe |
| **What valid issue it may hide** | A string classified as auto_safe by a previous stage (e.g., whitespace fix) may still have semantic issues that would be caught by AI review. |
| **Required test** | Feed a string with both a whitespace issue (auto_safe) and a semantic issue. Verify the semantic issue is not suppressed. |

### S4 — should_invoke_ai: deterministic fix skip
| Attribute | Value |
|---|---|
| **Location** | [ai_review.py:L340-342](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L340-L342) |
| **Why it exists** | Known-safe replacements don't need AI |
| **What valid issue it may hide** | Low risk — these are genuine known-safe fixes. But if a string has both a known-safe issue AND a semantic issue, the semantic issue type might be masked by the deterministic classification. |
| **Required test** | Feed a string with both `known_safe_replacement` and `semantic` issue types. Verify semantic issue survives. |

### S5 — Technical key filtering
| Attribute | Value |
|---|---|
| **Location** | [ai_review.py:L663](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ai_review.py#L663) |
| **Why it exists** | Technical keys (config.*, *_id, *_url, UUIDs) don't need translation review |
| **What valid issue it may hide** | Low risk — technical keys genuinely shouldn't be translated. But a key like `settings_id_verification_message` might be incorrectly classified as technical due to `_id` substring matching. |
| **Required test** | Feed a key with `_id` in the name that is actually a user-facing string. Verify it's not suppressed. |

### S6 — Semantic QC: status/informational string suppression
| Attribute | Value |
|---|---|
| **Location** | [ar_semantic_qc.py:L115-116](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_semantic_qc.py#L115-L116) |
| **Why it exists** | Prevents absurd candidates like "أضف تم حذف العنوان بنجاح" |
| **What valid issue it may hide** | Status strings that use wrong vocabulary (e.g., "تم أنقاذ" instead of "تم الحفظ" for "Saved successfully") are suppressed from candidate generation. The finding may still exist, but without a candidate it loses actionability. |
| **Required test** | Feed a status string with wrong vocabulary. Verify it appears in review queue even without a candidate. |

### S7 — Fix plan: missing candidate_value rejection
| Attribute | Value |
|---|---|
| **Location** | [apply_safe_fixes.py:L236-240](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/apply_safe_fixes.py#L236-L240) |
| **Why it exists** | Can't apply a fix without knowing what to change to |
| **What valid issue it may hide** | A real semantic issue without a generated candidate is silently dropped from the fix plan. The issue exists but becomes invisible in the fix/review workflow. |
| **Required test** | Feed a finding with no candidate. Verify it appears in the review queue even without a candidate value. |

### S8 — Enforcement layer: routing skip
| Attribute | Value |
|---|---|
| **Location** | [enforcement_layer.py:L53-74](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/enforcement_layer.py#L53-L74) |
| **Why it exists** | Route-based optimization — skip AI for auto_fix items, skip autofix for ai_review items |
| **What valid issue it may hide** | When routing is enabled, a finding routed to `auto_fix` is never seen by AI review. If the auto-fix is wrong, there's no second opinion. |
| **Required test** | Feed a finding with `route=auto_fix` that has a wrong suggestion. Verify it's caught by some downstream check. |

### S9 — Fix plan deduplication
| Attribute | Value |
|---|---|
| **Location** | [apply_safe_fixes.py:L460-471](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/fixes/apply_safe_fixes.py#L460-L471) |
| **Why it exists** | Prevents applying the same fix twice |
| **What valid issue it may hide** | Signature-based dedup (key, locale, issue_type, candidate_value) may merge findings from different detectors that happen to produce the same candidate. The provenance information is lost. |
| **Required test** | Feed two findings from different sources with the same candidate. Verify both provenances are preserved. |

---

## 5. Candidate Quality Audit

### C1 — Naive verb-prepending in ar_semantic_qc
| Issue | `build_semantic_candidate()` creates candidates by prepending an Arabic imperative verb to the existing Arabic text |
|---|---|
| **Location** | [ar_semantic_qc.py:L91-125](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_semantic_qc.py#L91-L125) |
| **Risk** | Creates structurally valid but semantically absurd candidates. E.g., "العنوان" → "أضف العنوان" (good for "Add Address"), but "الإعدادات المتقدمة" → "احفظ الإعدادات المتقدمة" is wrong if source is "Advanced Settings". |
| **Mitigations present** | Multi-action suppression (L103-104), status string suppression (L115-116), terminal punctuation handling (L121-124) |
| **Missing mitigations** | No check that the prepended verb matches the source intent. No check that the resulting Arabic is grammatically correct (verb agreement with noun gender/number). |

### C2 — AI-generated candidates lack deterministic quality gate
| Issue | AI suggestions pass through structural verification but not semantic quality verification |
|---|---|
| **Location** | [verification.py:verify_batch_fixes()](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L668-L812) |
| **Risk** | Structural checks (placeholders, newlines, HTML, glossary) are necessary but insufficient. A candidate that preserves all placeholders and uses glossary terms but changes the meaning of the sentence passes verification. |
| **Mitigations present** | Semantic acceptance gate (L727-734) catches concept injection, polarity mismatch, number mismatch, named entity mismatch, domain confusion, transliteration issues |
| **Missing mitigations** | No check that the candidate preserves the overall meaning. No check that the candidate uses appropriate Arabic register/tone for UI. No length-appropriateness check for mobile UI. |

### C3 — Empty candidates for detected issues
| Issue | Many findings are generated with `candidate_value=""` |
|---|---|
| **Location** | [ar_semantic_qc.py:L95-101](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/audits/ar_semantic_qc.py#L95-L101), L198 |
| **Risk** | Findings without candidates are harder to act on. Downstream, missing candidate causes fix plan rejection (S7). The issue is detected but becomes invisible in the fix workflow. |
| **Frequency** | High — `build_semantic_candidate()` returns empty string for: structural mismatches, high semantic risk, no missing actions, multi-action strings, status strings |

### C4 — Candidate violates glossary but passes fuzzy match
| Issue | `is_arabic_fuzzy_match()` strips Arabic morphological markers aggressively |
|---|---|
| **Location** | [verification.py:L568-595](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L568-L595) |
| **Risk** | A candidate using a morphological variant of a forbidden term may pass the fuzzy match check. E.g., if "رايدر" is forbidden, "الرايدرين" (with prefix ال and suffix ين) stripped to consonants might not match depending on the stripping logic. |

### C5 — Candidate same as current bad value
| Issue | When AI returns the current translation, it's silently dropped |
|---|---|
| **Location** | [verification.py:L706-707](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/ai/verification.py#L706-L707) |
| **Risk** | The AI might return the current text because (a) it thinks it's correct, (b) it can't think of a better alternative, or (c) the prompt didn't clearly ask for an alternative. In all cases, the original issue is silently suppressed. |

---

## 6. Confidence Calibration Audit

### Threshold Analysis

| Threshold | Value | Evidence Required | Assessment |
|---|---|---|---|
| `auto_fix` | confidence ≥ 0.8 AND `is_simple_fix` | `base(0.5) + simple_fix_bonus(0.3) + grammar(0.2) = 1.0` | **Too optimistic** — requires only category signal + is_simple_fix flag, no semantic verification |
| `manual_review` | confidence ≤ 0.3 | `base(0.5) - missing_suggestion(0.4) = 0.1` | **Reasonable** — missing suggestion is indeed a strong uncertainty signal |
| `ai_review` | 0.3 < confidence < 0.8 | Default fallback route | **Acceptable** — serves as the catch-all |

### Calibration Engine Issues

| Issue | Assessment |
|---|---|
| **Default mode is "shadow"** | CalibrationEngine defaults to shadow mode ([L325](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L325)), meaning calibration adjustments are computed but **not applied**. The feature is effectively inactive unless explicitly configured. |
| **Only downgrades, never upgrades** | Design constraint ([L16](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L16)) — auto_fix → ai_review is allowed, but ai_review → auto_fix is NOT. This is safe but means calibration can only reduce throughput, not improve it. |
| **max_adjustment capped at 0.05** | Very conservative ([L155](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L155)) — even with terrible acceptance rates, the threshold adjustment is tiny. This means miscalibration is slow to correct. |
| **No calibration state persisted** | Per-run only ([L18](file:///Users/waeldaaboul/L10n%20Audit%20Toolkit/l10n_audit/core/calibration_engine.py#L18)) — calibration starts fresh each run. Past runs' acceptance rates don't inform future thresholds. |

### Confidence Score Meaningfulness

The confidence score is **meaningful but incomplete**:

- **Meaningful**: It aggregates real evidence signals (semantic risk, placeholder integrity, glossary alignment, structural consistency, feedback metrics) into a deterministic score. Each contribution is tracked and explainable.
- **Incomplete**: The base of 0.5 with additive bonuses means a finding with zero evidence gets 50% confidence. The `is_simple_fix` flag combined with `simple_fix_bonus(+0.3)` alone can push confidence to 0.8, hitting the auto_fix threshold with no semantic evidence.
- **Critical gap**: There is no negative evidence for "this translation might be correct" — the system only scores issues, not correctness.

### Overconfident Auto-safe Paths

1. **Grammar + simple_fix → auto_fix**: A grammar finding with `is_simple_fix=True` gets `0.5 + 0.3 + 0.2 = 1.0` confidence → auto_fix. No semantic check.
2. **Whitespace/spacing → auto_safe**: Classified directly as `auto_safe` in `classify_issue()` without any confidence scoring.
3. **AI verified + small change → auto_safe**: AI suggestions with `verified=True` and small length difference are auto-applied.

### Missing Uncertainty States

The system has no explicit "uncertain" state. Routes are:
- `auto_fix` (high confidence) 
- `ai_review` (medium confidence)
- `manual_review` (low confidence)
- `dropped` (no action)

There is no "uncertain — cannot determine if correct or incorrect" state. This forces the system to always take a position, even when evidence is insufficient.

---

## 7. Precision Improvement Recommendations

> [!IMPORTANT]
> These are calibration and decision-quality improvements only. No new features, detectors, or models.

### R1 — Require semantic evidence before auto_fix
**Change**: In `evaluate_findings()`, require at least one semantic evidence signal (semantic_risk check, glossary alignment check, or placeholder integrity check) before allowing `RouteAction.AUTO_FIX`. If no semantic evidence exists, cap route at `AI_REVIEW`.

**Impact**: Prevents auto-fixing translations that were only checked for grammar/style without any semantic verification.

### R2 — Route short-ambiguous strings to review instead of skip
**Change**: In `should_invoke_ai()`, change the short-ambiguous-no-context path from `return False, SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT` to routing the finding to `manual_review` with the existing issue intact.

**Impact**: Short UI labels with potential domain-wrong translations will be reviewed instead of silently passed.

### R3 — Treat AI "same text" returns as uncertainty, not no-op
**Change**: In `verify_batch_fixes()`, when `suggestion.strip() == target_text.strip()`, create a finding with `needs_review=True` and `message="AI Review: could not determine a better translation"` instead of silently continuing.

**Impact**: Issues where AI returns the same text are surfaced for human review instead of disappearing.

### R4 — Add correctness verdict to AI prompt
**Change**: In `prompts.py`, modify the prompt to require the AI to return both a `translated_text` and a `verdict` field ("correct", "needs_improvement", "cannot_determine"). Use the verdict to inform routing.

**Impact**: Distinguishes between "AI agrees with current translation" and "AI couldn't think of an improvement" — currently both produce the same outcome (suppression).

### R5 — Tighten auto_safe classification for AI suggestions
**Change**: In `classify_issue()`, require AI suggestions to have `semantic_gate_status == "accept"` (not just `verified == True`) before classifying as `auto_safe`. Currently, `verified=True` comes from structural checks only.

**Impact**: Prevents auto-applying AI suggestions that passed structural verification but were marked "suspicious" by the semantic gate.

### R6 — Reduce missing_suggestion_penalty for style issues
**Change**: In `_build_evidence_contributions()`, reduce the `missing_suggestion_penalty` from -0.4 to -0.2 when `issue_category == "style"`. Style issues without suggestions are common and shouldn't force manual review.

**Impact**: Reduces false reviews for routine style findings.

### R7 — Preserve findings without candidates in review queue
**Change**: In `build_fix_plan()`, don't reject findings that lack a `candidate_value`. Instead, include them in the review queue with `candidate_value=""` and `classification="review_required"`.

**Impact**: Ensures detected issues aren't silently dropped just because no fix was generated.

### R8 — Enable calibration in enforce mode by default
**Change**: Change the default calibration mode from `shadow` to `enforce` and set `respect_routing` to `True` by default.

**Impact**: The routing and calibration infrastructure actually affects decisions instead of being inert metadata.

### R9 — Tighten `is_arabic_fuzzy_match()` consonant matching
**Change**: Reduce the length tolerance from ±3 to ±2 characters. Add a minimum consonant skeleton length of 3 (currently 2) to reduce false matches on very short roots.

**Impact**: Reduces false glossary compliance passes from overly permissive fuzzy matching.

### R10 — Add contradictory signal escalation
**Change**: In `_build_evidence_contributions()`, add cross-evidence escalation: if `glossary_alignment == "approved"` but `semantic_risk == "high"`, escalate to manual_review regardless of confidence score.

**Impact**: Catches cases where a translation uses correct glossary terms but in the wrong semantic context.

---

## 8. Required Tests

### T1 — Wrong Translation Does Not Pass Silently
```
Given: Arabic translation that is grammatically correct, placeholder-preserving, 
       glossary-compliant, but semantically wrong 
       (e.g., "Settings" → "إعدادات الطقس")
Expected: Translation appears in review queue
Current: Translation passes silently (no detector fires)
```

### T2 — Short Domain-Wrong Labels Are Not Skipped
```
Given: Source "Cancel", Arabic "شطب" (wrong domain — should be "إلغاء"), 
       no glossary, no context
Expected: Translation appears in review queue
Current: Skipped by should_invoke_ai() short-ambiguous gate
```

### T3 — AI Same-Text Return Creates Review Finding
```
Given: Known-bad translation, AI returns same text as current
Expected: Original issue survives in review queue with uncertainty flag
Current: Issue is silently dropped
```

### T4 — Auto-fix Requires Semantic Evidence
```
Given: Grammar finding with is_simple_fix=True, no semantic evidence
Expected: Route to ai_review (not auto_fix)
Current: Routes to auto_fix with confidence 1.0
```

### T5 — Correct Short Arabic Labels Not Falsely Flagged
```
Given: Source "Address", Arabic "العنوان" (correct short label)
Expected: Not flagged for review
Current: May be flagged by sentence_shape_mismatch
```

### T6 — Missing Candidates Don't Hide Issues
```
Given: Semantic issue detected, no candidate generated
Expected: Issue appears in review queue with empty candidate
Current: Issue may be dropped from fix plan
```

### T7 — Contradictory Signals Are Escalated
```
Given: Finding with glossary_alignment="approved" but semantic_risk="high"
Expected: Route to manual_review
Current: Glossary bonus offsets semantic penalty, may route to ai_review
```

### T8 — Bad Candidates Are Rejected
```
Given: AI candidate that preserves placeholders but changes meaning 
       (polarity flip, missing negation)
Expected: Candidate rejected by semantic gate
Current: Correctly handled by _check_polarity() — verify with test
```

### T9 — No-op Suppression Preserves Original Issue
```
Given: Issue where candidate_value == current_value
Expected: Issue survives in review queue
Current: Issue is dropped from fix plan (missing candidate_value)
```

### T10 — Calibration Enforce Mode Works End-to-End
```
Given: Calibration enabled in enforce mode, feedback shows 30% auto_fix rejection
Expected: auto_fix threshold raised, some auto_fix items downgraded to ai_review
Current: Works correctly in enforce mode, but mode defaults to shadow (no effect)
```

### T11 — CAMeL/LanguageTool Contradictions Handled Safely
```
Given: CAMeL signals indicate morphological error, LanguageTool reports no issue
Expected: Contradiction raises uncertainty, routes to review
Current: CAMeL signals are shadow-only, contradiction is invisible
```

### T12 — Glossary Fuzzy Match Does Not Miss Violations
```
Given: Forbidden Arabic term with prefix+suffix morphological variant
Expected: Variant is caught by fuzzy match
Current: May pass if consonant skeleton difference > 3 chars
```

---

## 9. Final Recommendation

**Recommended action: Patch multiple decision layers**

The audit reveals that the toolkit has **no single catastrophic flaw** but rather a **constellation of decision-quality issues** across multiple layers:

1. **Decision Engine**: Patch confidence scoring to require semantic evidence before auto_fix (R1). This is the highest-impact, lowest-risk change.

2. **AI Review Gating**: Patch short-ambiguous skip to route to review instead of silent pass (R2). Second highest impact.

3. **Suppression Logic**: Patch AI same-text suppression to preserve original issue (R3). Patch fix plan to accept findings without candidates (R7).

4. **AI Prompt**: Add correctness verdict to distinguish "correct" from "no issue detected" (R4). Medium effort, high impact.

5. **Auto-safe Classification**: Tighten to require semantic gate acceptance for AI suggestions (R5).

6. **Calibration Activation**: Enable calibration in enforce mode by default (R8). Zero-risk change that activates existing infrastructure.

**Do NOT** collect evaluation data first — the issues identified are structural and reproducible from code analysis alone. Every recommendation above can be validated with deterministic unit tests before deployment.

**Priority order**: R1 → R2 → R3 → R7 → R5 → R4 → R8 → R6 → R9 → R10
