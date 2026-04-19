#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import re
import json
import concurrent.futures
from pathlib import Path
from typing import Any

logger = logging.getLogger("l10n_audit.ai_review")

from l10n_audit.core.audit_runtime import (
    load_locale_mapping,
    load_runtime,
    write_json,
)
from l10n_audit.core.workspace import read_json
from l10n_audit.ai.provider import AIProviderError
from l10n_audit.ai.provider import request_ai_review
from l10n_audit.ai.prompts import get_review_prompt
from l10n_audit.ai.verification import verify_batch_fixes
from l10n_audit.core.decision_engine import is_routing_enabled
from l10n_audit.core.routing_metrics import RoutingMetrics

from l10n_audit.core.artifact_resolver import (
    resolve_final_report_path,
    resolve_review_machine_queue_json_path,
    resolve_review_queue_json_path
)
from l10n_audit.core.ai_trace import (
    SKIP_REASON_AUTO_SAFE_CLASSIFICATION,
    SKIP_REASON_DETERMINISTIC_FIX,
    SKIP_REASON_FORMATTING_ONLY,
    SKIP_REASON_NON_LINGUISTIC_SOURCE,
    SKIP_REASON_PLACEHOLDER_ONLY,
    SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT,
    emit_ai_decision_trace,
    emit_ai_fallback,
    get_metrics,
    is_ai_debug_mode,
    reset_metrics,
)

def load_issues(runtime):
    """Read existing local audits with role-based priority (Phase 9).
    
    Priority:
      1. final_audit_report.json (Source of truth for entire run)
      2. review_machine_queue.json (Explicit machine-consumer artifact)
      3. review_queue.json (Legacy fallback / Compatibility)
    """
    # 1. Final report
    report_path = resolve_final_report_path(runtime)
    
    # 2. Machine queue (preferred source)
    if not report_path.exists():
        report_path = resolve_review_machine_queue_json_path(runtime)
        
    # 3. Legacy fallback
    if not report_path.exists():
        report_path = resolve_review_queue_json_path(runtime)
        
    if not report_path.exists():
        return []
        
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return data.get("findings", []) + data.get("issues", []) + data.get("review_queue", []) + data.get("rows", [])
    except Exception as e:
        logger.error(f"Failed to load issues from {report_path}: {e}")
        return []

def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-enabled", action="store_true", help="Enable AI review")
    parser.add_argument("--ai-api-key", help="API Key (or use env)")
    parser.add_argument("--ai-api-base", help="API Base URL")
    parser.add_argument("--ai-model", help="AI Model name")
    parser.add_argument("--out-json", help="Output JSON path")
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    
    args, unknown = parser.parse_known_args()

    if not args.ai_enabled:
        print("AI Review is disabled. Use --ai-enabled to run.")
        return

    config = {
        "api_key": args.ai_api_key or os.getenv(os.getenv("AI_API_KEY_ENV", "OPENAI_API_KEY")),
        "api_base": args.ai_api_base or os.getenv("AI_API_BASE", "https://api.openai.com/v1"),
        "model": args.ai_model or os.getenv("AI_API_MODEL", "gpt-4o-mini")
    }

    if not config["api_key"]:
        print("Error: AI API Key not found. Set OPENAI_API_KEY or use --ai-api-key")
        return

    # 1. Load Issues
    all_issues = load_issues(runtime)
    if not all_issues:
        print("No prior issues found. AI Review skipped.")
        return
        
    en_data = load_locale_mapping(Path(args.en), runtime, "en")
    ar_data = load_locale_mapping(Path(args.ar), runtime, "ar")
        
    # Build unique flawed keys issues dict
    flawed_keys = {}
    routing_metrics_main = RoutingMetrics()
    
    for issue in all_issues:
        route = issue.get("decision", {}).get("route", "unknown")
        routing_metrics_main.record(route)
        
        if is_routing_enabled(runtime):
            if route != "ai_review":
                routing_metrics_main.record_ai_skip()
                logger.debug("ROUTING ENFORCEMENT (ai_review main): Skipping key='%s' because route is '%s' (not ai_review)", issue.get("key"), route)
                continue
                
        k = issue.get("key")
        if not k: 
            continue
            
        src = str(en_data.get(k, ""))
        target = str(ar_data.get(k, ""))
        if not src or not target:
            continue
            
        desc = issue.get("message") or issue.get("description") or issue.get("issue_type") or "Unknown issue"
        if k in flawed_keys:
            flawed_keys[k]["identified_issue"] += f" | {desc}"
        else:
            flawed_keys[k] = {
                "key": k,
                "source": src,
                "current_translation": target,
                "identified_issue": desc
            }
            
    batch_items = list(flawed_keys.values())
    
    if is_routing_enabled(runtime):
        logger.info("Routing Metrics [ai_review main]: %s", routing_metrics_main.to_dict())
        try:
            if hasattr(runtime, "metadata"):
                runtime.metadata["routing_metrics"] = routing_metrics_main.to_dict()
        except Exception:
            pass
            
    if not batch_items:
        print("No valid flawed keys with source/target found.")
        return

    # 2. Strict Glossary Integration
    glossary_data = {}
    try:
        if getattr(runtime, "config_dir", None):
            glossary_path = runtime.config_dir / "glossary.json"
            if glossary_path.exists():
                glossary_data = json.loads(glossary_path.read_text(encoding="utf-8"))
    except Exception as e:
        logging.warning(f"Failed to load glossary: {e}")

    glossary_terms = {}
    if glossary_data and "terms" in glossary_data:
        for t in glossary_data["terms"]:
            term_en = t.get("term_en")
            term_ar = t.get("approved_ar")
            if term_en and term_ar:
                glossary_terms[term_en] = {
                    "translation": term_ar,
                    "notes": t.get("definition", "")
                }

    # 3. Batch Processing
    CHUNK_SIZE = 20
    chunks = [batch_items[i:i + CHUNK_SIZE] for i in range(0, len(batch_items), CHUNK_SIZE)]
    
    print(f"Starting Glossary-Driven AI Review for {len(batch_items)} items across {len(chunks)} batches...")

    findings = []
    
    def process_chunk(chunk):
        prompt = get_review_prompt(chunk, glossary_terms)
        response = request_ai_review(prompt, config)
        if response and "fixes" in response:
            return verify_batch_fixes(chunk, response["fixes"])
        return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chunk = {executor.submit(process_chunk, chunk): chunk for chunk in chunks}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_chunk)):
            try:
                batch_findings = future.result()
                findings.extend(batch_findings)
                print(f"  Processed batch {i+1}/{len(chunks)} - Found {len(batch_findings)} safe fixes", end="\\r")
            except Exception as exc:
                logging.error(f"Batch generated an exception: {exc}")

    print(f"\\nDone. AI suggestions found: {len(findings)}")
    
    out_path = args.out_json or str(runtime.results_dir / "ai_review_report.json")
    write_json({"findings": findings}, Path(out_path))
    print(f"Report saved to: {out_path}")

if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def chunk_issues(issues, batch_size=50):
    """Split issues into smaller chunks for batch processing."""
    for i in range(0, len(issues), batch_size):
        yield issues[i:i + batch_size]


def _extract_context_text(issue: dict[str, Any]) -> str | None:
    extra = issue.get("extra") if isinstance(issue.get("extra"), dict) else {}
    decision = issue.get("decision") if isinstance(issue.get("decision"), dict) else {}
    candidates = (
        issue.get("context"),
        issue.get("ui_context"),
        issue.get("screen"),
        issue.get("note"),
        extra.get("context"),
        decision.get("context"),
    )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text, flags=re.UNICODE))


def _extract_placeholders_for_payload(source_text: str) -> list[str]:
    from l10n_audit.core.audit_runtime import extract_placeholders

    return sorted(extract_placeholders(source_text))


def _build_glossary_translation_map(raw_glossary: dict[str, Any]) -> dict[str, str]:
    """Flatten glossary terms to {english_term: approved_translation}."""
    terms: dict[str, str] = {}
    for item in raw_glossary.get("terms", []) if isinstance(raw_glossary, dict) else []:
        if not isinstance(item, dict):
            continue
        term_en = str(item.get("term_en", "")).strip()
        approved_ar = str(item.get("approved_ar", "")).strip()
        if term_en and approved_ar:
            terms[term_en] = approved_ar
    return terms


def _relevant_glossary_for_source(source_text: str, glossary_map: dict[str, str]) -> dict[str, str]:
    """Return only glossary entries that are relevant to this source string."""
    if not source_text or not glossary_map:
        return {}
    lowered_source = source_text.lower()
    matched: dict[str, str] = {}
    for term_en, approved_ar in glossary_map.items():
        if term_en.lower() in lowered_source:
            matched[term_en] = approved_ar
    return matched


def _requires_semantic_repair(finding: dict[str, Any]) -> bool:
    """Detect deterministic semantic-repair signals without consulting AI."""
    if str(finding.get("route", "")).strip().lower() == "ai_review":
        return True

    issue_types = [str(it).lower() for it in finding.get("issue_types", []) if it]
    issue_text = " ".join(
        [
            str(finding.get("identified_issue", "") or "").lower(),
            str(finding.get("issue_type", "") or "").lower(),
        ]
    )
    semantic_markers = (
        "semantic",
        "meaning",
        "context",
        "quality",
        "needs_manual_review",
        "manual_review",
        "ar_qc",
    )
    if any(marker in issue_text for marker in semantic_markers):
        return True
    return any(any(marker in issue_type for marker in semantic_markers) for issue_type in issue_types)


def should_invoke_ai(finding, context) -> tuple[bool, str | None]:
    """Deterministic gate for live AI invocation control.

    Returns
    -------
    (invoke, skip_reason)
        ``invoke`` is ``True`` when the AI should be called for this finding.
        ``skip_reason`` is one of the ``SKIP_REASON_*`` constants when
        ``invoke`` is ``False``, and ``None`` otherwise.
    """
    from l10n_audit.core.audit_runtime import is_likely_technical_text

    source_text = str(finding.get("source_text", "") or "").strip()
    current_text = finding.get("current_text")
    issue_types = {str(it).strip().lower() for it in finding.get("issue_types", []) if str(it).strip()}
    issue_type = str(finding.get("issue_type", "") or "").strip().lower()
    if issue_type:
        issue_types.add(issue_type)

    # Hard block: empty or non-linguistic source does not benefit from AI.
    if not source_text or is_likely_technical_text(source_text):
        return False, SKIP_REASON_NON_LINGUISTIC_SOURCE

    # Placeholder / formatting issues — deterministic rules already handle them.
    _is_placeholder = bool(issue_types.intersection({"placeholder-only"})) or any(
        "placeholder" in it for it in issue_types
    )
    _is_formatting = bool(
        issue_types.intersection({"formatting", "whitespace", "spacing", "punctuation"})
    )
    if _is_placeholder or _is_formatting:
        return False, SKIP_REASON_PLACEHOLDER_ONLY if _is_placeholder else SKIP_REASON_FORMATTING_ONLY

    deterministic_issue_types = {"known_safe_replacement", "safe_normalization", "normalization"}
    if issue_types.intersection(deterministic_issue_types):
        return False, SKIP_REASON_DETERMINISTIC_FIX

    if str(finding.get("classification", "")).strip().lower() == "auto_safe":
        return False, SKIP_REASON_AUTO_SAFE_CLASSIFICATION

    current_text_str = str(current_text or "").strip()
    missing_translation = (
        not current_text_str
        or current_text_str == "[MISSING]"
        or any(it.startswith("missing") for it in issue_types)
        or "empty_ar" in issue_types
    )
    if missing_translation:
        return True, None

    glossary = finding.get("glossary") if isinstance(finding.get("glossary"), dict) else {}
    has_context = bool(str(finding.get("context", "") or "").strip())
    short_ambiguous_threshold = int(context.get("short_ambiguous_threshold", 4)) if isinstance(context, dict) else 4
    if _word_count(source_text) <= short_ambiguous_threshold and not glossary and not has_context:
        return False, SKIP_REASON_SHORT_AMBIGUOUS_NO_CONTEXT

    return _requires_semantic_repair(finding), None


def _build_ai_input_payload(
    finding: dict[str, Any],
    *,
    locale: str,
    glossary_map: dict[str, str],
) -> dict[str, Any]:
    source_text = str(finding.get("original_source") or finding.get("source_text") or finding.get("source") or "")
    current_text_raw = finding.get("current_translation")
    current_text = None if current_text_raw is None else str(current_text_raw)
    payload = {
        "key": str(finding.get("key", "")),
        "source_text": source_text,
        "current_text": current_text,
        "locale": locale,
        "placeholders": _extract_placeholders_for_payload(source_text),
        "context": finding.get("context"),
        "glossary": _relevant_glossary_for_source(source_text, glossary_map),
    }
    return {
        **finding,
        **payload,
        # Keep legacy fields so downstream verification/report paths remain unchanged.
        "source": finding.get("source", source_text),
        "current_translation": current_text or "",
    }


def _provider_reason_text(reason: str) -> str:
    reason_map = {
        "provider_timeout": "provider timeout",
        "provider_connection_error": "provider connection error",
        "provider_rate_limited": "rate limited — applying backoff",
        "provider_api_error": "provider API error",
        "provider_invalid_response": "provider invalid response",
    }
    return reason_map.get(reason, "provider failure")


def _coerce_int_option(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        parsed = default
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            parsed = default
    else:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _coerce_float_option(value: Any, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool):
        parsed = default
    elif isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            parsed = default
    else:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed

# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options, *, ai_provider=None, previous_issues=None, en_data: dict | None = None, ar_data: dict | None = None) -> list:
    """Run AI review stage and return a list of :class:`AuditIssue`.

    Parameters
    ----------
    ai_provider:
        Optional :class:`~l10n_audit.core.ai_protocol.AIProvider`.
        Defaults to the production LiteLLM provider.
    previous_issues:
        Optional list of issues from previous stages in the same run.
    en_data:
        Optional pre-hydrated canonical EN locale dict (Phase B injection).
    ar_data:
        Optional pre-hydrated canonical AR locale dict (Phase B injection).
    """
    import time
    from l10n_audit.models import issue_from_dict
    from l10n_audit.exceptions import AIConfigError

    if not options.ai_review.enabled:
        # Explicitly requested ai-review stage but ai_review.enabled is False
        raise AIConfigError(
            "AI review requested but not enabled. Use --ai-enabled or set it in config."
        )

    from l10n_audit.core.validators import validate_ai_config
    ai_config = validate_ai_config(
        ai_enabled=True,
        ai_api_key=None, # Not explicitly passed here, validator can fetch from env
        ai_api_key_env=options.ai_review.api_key_env,
        ai_model=options.ai_review.model,
        ai_api_base=None, # Fetched from env or platform default
        ai_provider=options.ai_review.provider,
    )
    ai_config["request_timeout_seconds"] = getattr(options.ai_review, "request_timeout_seconds", 60)

    if ai_provider is None:
        from l10n_audit.core.ai_factory import get_ai_provider
        ai_provider = get_ai_provider(options.ai_review.provider)

    # Load existing issues to review (In-memory if available, else Disk)
    if previous_issues is not None:
        # Ensure they are dicts for the logic below
        all_issues = [i.to_dict() if hasattr(i, "to_dict") else i for i in previous_issues]
        logger.debug("[AI] Consuming %d issues from in-memory tracker.", len(all_issues))
    else:
        all_issues = load_issues(runtime)
        
    if not all_issues:
        return []

    if en_data is None or ar_data is None:
        logger.warning(
            "Deprecation: ai_review invoked without paired canonical state. "
            "Falling back to legacy internal lookup."
        )
        en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
        ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    # Load glossary once and keep both raw and normalized forms.
    raw_glossary: dict[str, Any] = {}
    try:
        if getattr(runtime, "config_dir", None) and (runtime.config_dir / "glossary.json").exists():
            raw_glossary = json.loads((runtime.config_dir / "glossary.json").read_text(encoding="utf-8"))
    except Exception:
        raw_glossary = {}
    glossary_translation_map = _build_glossary_translation_map(raw_glossary)

    # Build candidate batch with deterministic noise filtering
    flawed_keys: dict = {}
    technical_prefixes = ("config", "setup", "uuid", "error_code", "zone")
    technical_substr = ("_id", "_url")
    uuid_pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)

    from l10n_audit.core.enforcement_layer import EnforcementController
    enforcer = EnforcementController(runtime)

    for issue in all_issues:
        decision = issue.get("decision", {})
        route = decision.get("route")

        enforcer.record(route)
        enforcer.record_adaptive(decision.get("confidence", 0.5), decision.get("risk", "low"))
        
        if not enforcer.should_process(route, "ai"):
            enforcer.record_skip("ai")
            logger.debug(
                "AI OPTIMIZATION: Skipping key='%s' route='%s'",
                issue.get("key"),
                route
            )
            continue

        k = str(issue.get("key", ""))
        if not k or k.endswith("."): # Skip empty keys or parent keys
            continue
            
        # Skip technical keys (Recovery & Enhancement step 4)
        k_lower = k.lower()
        if k_lower.startswith(technical_prefixes) or any(s in k_lower for s in technical_substr) or uuid_pattern.search(k):
            continue

        src = str(en_data.get(k, ""))
        target = str(ar_data.get(k, ""))
        if not src or not target:
            continue
            
        # Skip likely technical text (slugs, paths, IDs)
        from l10n_audit.core.audit_runtime import is_likely_technical_text
        from l10n_audit.fixes.apply_safe_fixes import preprocess_source_text
        if is_likely_technical_text(src) or is_likely_technical_text(target):
            continue

        desc = issue.get("message") or issue.get("description") or issue.get("issue_type") or "Unknown issue"
        issue_type = str(issue.get("issue_type", "")).strip().lower()
        issue_context = _extract_context_text(issue)
        if k in flawed_keys:
            flawed_keys[k]["identified_issue"] += f" | {desc}"
            if issue_type:
                flawed_keys[k]["issue_types"].add(issue_type)
            if issue_context and not flawed_keys[k].get("context"):
                flawed_keys[k]["context"] = issue_context
        else:
            cleaned_src = preprocess_source_text(src)
            flawed_keys[k] = {
                "key": k,
                "source": cleaned_src,
                "original_source": src,
                "current_translation": target,
                "identified_issue": desc,
                "issue_type": issue_type,
                "issue_types": {issue_type} if issue_type else set(),
                "context": issue_context,
                "classification": str(issue.get("classification", "")),
                "route": route,
            }

    # Add missing keys if translate_missing is enabled
    if options.ai_review.translate_missing:
        from l10n_audit.fixes.apply_safe_fixes import preprocess_source_text
        for k, v in en_data.items():
            if k not in ar_data or not str(ar_data.get(k, "")).strip():
                if k not in flawed_keys:
                    v_str = str(v)
                    cleaned_v = preprocess_source_text(v_str)
                    flawed_keys[k] = {
                        "key": k,
                        "source": cleaned_v,
                        "original_source": v_str,
                        "current_translation": "[MISSING]",
                        "identified_issue": "Missing translation (Auto-translate requested)",
                        "issue_type": "missing_translation",
                        "issue_types": {"missing_translation"},
                        "context": None,
                        "classification": "",
                        "route": "ai_review",
                    }

    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    invocation_context = {"short_ambiguous_threshold": 4}
    # Phase 9: reset module-level metrics for this run so each invocation of
    # run_stage starts with a clean slate.
    reset_metrics()
    batch_items = []
    for item in flawed_keys.values():
        payload = _build_ai_input_payload(item, locale=target_locale, glossary_map=glossary_translation_map)
        payload["issue_types"] = sorted({str(it) for it in payload.get("issue_types", []) if str(it).strip()})
        invoke_ai, skip_reason = should_invoke_ai(payload, invocation_context)
        _item_key = payload.get("key", "")
        if invoke_ai:
            batch_items.append(payload)
            get_metrics().record_invoked()
            if is_ai_debug_mode():
                logger.debug("AI INPUT PAYLOAD [key=%s]: %s", _item_key, payload)
        else:
            get_metrics().record_skipped()
            emit_ai_decision_trace(
                key=_item_key,
                invoked=False,
                skip_reason=skip_reason,
                payload=payload,
            )
            logger.debug(
                "AI INVOCATION CONTROL: Skipping key='%s' skip_reason='%s'",
                _item_key,
                skip_reason,
            )
    
    if enforcer.enabled:
        logger.info("Routing Metrics [ai_review run_stage]: %s", enforcer.metrics.to_dict())
        enforcer.save_metrics(runtime)
            
    if not batch_items:
        # Phase 9: store metrics even when all keys were skipped.
        get_metrics().log_summary()
        try:
            if hasattr(runtime, "metadata"):
                runtime.metadata["ai_decision_metrics"] = get_metrics().to_dict()
                runtime.metadata["ai_review_status"] = {
                    "status": "skipped",
                    "batches_total": 0,
                    "provider_failures": 0,
                    "degraded": False,
                }
        except Exception:
            pass
        return []

    # --- Phase 10: Conflict Resolution (Governance Layer) ---
    from l10n_audit.core.conflict_resolution import get_conflict_resolver, MutationRecord
    resolver = get_conflict_resolver(runtime)
    
    # 1. Pre-register high-priority mutations (auto_fix) that already exist
    for issue in all_issues:
        route = issue.get("decision", {}).get("route")
        if route == "auto_fix":
            k = issue.get("key")
            if k:
                resolver.register(MutationRecord(
                    key=k,
                    original_text=str(en_data.get(k, issue.get("source", ""))),
                    new_text=str(issue.get("suggested_fix") or issue.get("suggestion") or ""),
                    offset=issue.get("offset", -1),
                    length=issue.get("error_length", 0),
                    source="existing_autofix",
                    priority=3
                ))

    # Process in batches using the injected AI provider
    all_fixes: list[dict] = []
    batches = list(chunk_issues(batch_items, batch_size=options.ai_review.batch_size))
    max_consecutive_failures = _coerce_int_option(
        getattr(options.ai_review, "max_consecutive_failures", 3),
        3,
        minimum=1,
    )
    max_consecutive_rate_limits = _coerce_int_option(
        getattr(options.ai_review, "max_consecutive_rate_limits", 2),
        2,
        minimum=1,
        maximum=3,
    )
    inter_batch_delay_seconds = _coerce_float_option(
        getattr(options.ai_review, "inter_batch_delay_seconds", 0.5),
        0.5,
        minimum=0.0,
    )
    consecutive_failures = 0
    consecutive_rate_limits = 0
    provider_failures = 0
    provider_usage = {
        "requests_sent": 0,
        "rate_limit_failures": 0,
        "retries_attempted": 0,
        "inter_batch_delay_applied": 0,
    }

    print(f"\nAI Review: processing {len(batches)} batch(es)...")

    for i, batch in enumerate(batches, start=1):
        provider_usage["requests_sent"] += 1
        should_stop = False
        try:
            # Pass BOTH glossary_terms (for prompt) and raw_glossary (for validation)
            fixes = ai_provider.review_batch(batch, ai_config, glossary=raw_glossary)
            consecutive_failures = 0
            consecutive_rate_limits = 0
            
            # 2. Register AI fixes with Priority 2
            for f in fixes:
                k = f.get("key")
                if not k:
                    all_fixes.append(f)
                    continue
                
                record = MutationRecord(
                    key=k,
                    original_text=str(en_data.get(k, "")),
                    new_text=str(f.get("suggestion") or ""),
                    offset=f.get("offset", -1),
                    length=f.get("error_length", 0),
                    source="ai_review",
                    priority=2
                )
                if resolver.register(record):
                    all_fixes.append(f)
                else:
                    logger.warning("AI CONFLICT: Skipping AI suggestion for key '%s' due to priority override.", k)
            
        except AIProviderError as exc:
            provider_failures += 1
            consecutive_failures += 1
            if exc.category == "provider_rate_limited":
                consecutive_rate_limits += 1
                provider_usage["rate_limit_failures"] += 1
            else:
                consecutive_rate_limits = 0
            _details = {
                "batch_index": i,
                "batch_size": len(batch),
                "consecutive_failures": consecutive_failures,
                "consecutive_rate_limits": consecutive_rate_limits,
            }
            if is_ai_debug_mode() and exc.details:
                _details["provider_error"] = exc.details
            emit_ai_fallback(key=f"batch:{i}", reason=exc.category, details=_details)
            details = exc.details if isinstance(exc.details, dict) else {}
            attempt = details.get("attempt")
            max_attempts = details.get("max_attempts")
            if isinstance(attempt, int) and attempt > 1:
                provider_usage["retries_attempted"] += attempt - 1
            if exc.category == "provider_rate_limited" and attempt is not None and max_attempts is not None:
                print(f"AI Review: batch {i}/{len(batches)} rate limited — applying backoff (attempt {attempt}/{max_attempts})")
            print(f"AI Review: batch {i}/{len(batches)} failed [{exc.category}]")
            if is_ai_debug_mode():
                logger.exception("AI review batch %d provider failure [%s]", i, exc.category)
            else:
                logger.debug("AI review batch %d failed [%s]", i, exc.category)
            if consecutive_rate_limits >= max_consecutive_rate_limits:
                print("AI Review: rate limited — stopping remaining batches after repeated provider throttling")
                should_stop = True
            elif consecutive_failures >= max_consecutive_failures:
                print(f"AI Review: stopping after {consecutive_failures} consecutive provider failures")
                should_stop = True
        except Exception as exc:
            provider_failures += 1
            consecutive_failures += 1
            consecutive_rate_limits = 0
            emit_ai_fallback(
                key=f"batch:{i}",
                reason="provider_api_error",
                details={"batch_index": i, "batch_size": len(batch), "error_type": type(exc).__name__},
            )
            print(f"AI Review: batch {i}/{len(batches)} failed [provider_api_error]")
            if is_ai_debug_mode():
                logger.exception("AI review batch %d failed with unexpected provider error", i)
            else:
                logger.debug("AI review batch %d failed [provider_api_error]", i)
            if consecutive_failures >= max_consecutive_failures:
                print(f"AI Review: stopping after {consecutive_failures} consecutive provider failures")
                should_stop = True
        if should_stop:
            break
        if i < len(batches):
            time.sleep(inter_batch_delay_seconds)
            provider_usage["inter_batch_delay_applied"] += 1

    if provider_failures:
        if all_fixes:
            print("AI Review: completed with degraded provider responses; retained successful earlier results.")
        else:
            print("AI Review: provider failures detected; continuing run without AI suggestions.")

    # Update metrics in metadata
    try:
        if hasattr(runtime, "metadata"):
            metrics = resolver.summarize()
            if "conflict_metrics" in runtime.metadata:
                # Merge with existing metrics (e.g. from previous stages in same run)
                m = runtime.metadata["conflict_metrics"]
                m["conflicts_detected"] += metrics["conflicts_detected"]
                m["conflicts_resolved"] += metrics["conflicts_resolved"]
                m["rejected_low_priority"] += metrics["rejected_low_priority"]
            else:
                runtime.metadata["conflict_metrics"] = metrics
            runtime.metadata["ai_review_status"] = {
                "status": "degraded" if provider_failures else "ok",
                "batches_total": len(batches),
                "provider_failures": provider_failures,
                "degraded": bool(provider_failures),
                "provider_usage": provider_usage,
            }
    except Exception:
        pass

    if options.write_reports:
        out_dir = options.effective_output_dir(runtime.results_dir) / ".cache" / "raw_tools" / "ai_review"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "ai_review_report.json"
        try:
            write_json({"findings": all_fixes}, out_path)
        except Exception as exc:
            logging.warning("Failed to write AI review report: %s", exc)

    normalised = [{**f, "issue_type": "ai_suggestion", "source": "ai_review"} for f in all_fixes]
    # --- Phase 7C Slice 5: normalize output shape before downstream model ---
    from l10n_audit.core.audit_output_adapter import normalize_audit_finding

    def _ai_review_to_adapter_shape(row: dict) -> dict:
        """Additive shim: map ai_review bespoke fields into adapter-compatible names.

        target     → old  → detected_value   (live AR value at detection time)
        suggestion →      → candidate_value  (handled natively by adapter 3rd fallback)

        All original fields (target, suggestion, verified, original_source) are
        preserved via **row so they land in _raw_metadata via the adapter.
        """
        return {
            **row,
            "old": row.get("target", ""),   # live AR target → detected_value
        }

    # Phase 9: emit AI decision summary and store metrics in runtime metadata.
    get_metrics().log_summary()
    try:
        if hasattr(runtime, "metadata"):
            runtime.metadata["ai_decision_metrics"] = get_metrics().to_dict()
    except Exception:
        pass

    normalized = [
        normalize_audit_finding(
            _ai_review_to_adapter_shape(r),
            audit_source="ai_review",
            locale="ar",
        )
        for r in normalised
    ]
    return [issue_from_dict(r) for r in normalized]
