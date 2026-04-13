#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import re
import json
import concurrent.futures
from pathlib import Path

logger = logging.getLogger("l10n_audit.ai_review")

from l10n_audit.core.audit_runtime import (
    load_locale_mapping,
    load_runtime,
    write_json,
)
from l10n_audit.core.workspace import read_json
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

# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options, *, ai_provider=None, previous_issues=None) -> list:
    """Run AI review stage and return a list of :class:`AuditIssue`.

    Parameters
    ----------
    ai_provider:
        Optional :class:`~l10n_audit.core.ai_protocol.AIProvider`.
        Defaults to the production LiteLLM provider.
    previous_issues:
        Optional list of issues from previous stages in the same run.
    """
    import os
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

    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    # Build batch with noise filtering
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
        if k in flawed_keys:
            flawed_keys[k]["identified_issue"] += f" | {desc}"
        else:
            cleaned_src = preprocess_source_text(src)
            flawed_keys[k] = {
                "key": k,
                "source": cleaned_src,
                "original_source": src,
                "current_translation": target,
                "identified_issue": desc
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
                        "identified_issue": "Missing translation (Auto-translate requested)"
                    }

    batch_items = list(flawed_keys.values())
    
    if enforcer.enabled:
        logger.info("Routing Metrics [ai_review run_stage]: %s", enforcer.metrics.to_dict())
        enforcer.save_metrics(runtime)
            
    if not batch_items:
        return []

    # Load glossary
    glossary_terms: dict = {}
    try:
        if getattr(runtime, "config_dir", None) and (runtime.config_dir / "glossary.json").exists():
            import json as _json
            glossary_data = _json.loads((runtime.config_dir / "glossary.json").read_text(encoding="utf-8"))
            for t in glossary_data.get("terms", []):
                if t.get("term_en") and t.get("approved_ar"):
                    glossary_terms[t["term_en"]] = {"translation": t["approved_ar"], "notes": t.get("definition", "")}
    except Exception:
        pass

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
    
    # Load raw glossary for strict validation pass
    raw_glossary = {}
    try:
        if (runtime.config_dir / "glossary.json").exists():
             import json as _json
             raw_glossary = _json.loads((runtime.config_dir / "glossary.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    # Display interactive waiting message
    print("\n🚀 Sending review request to AI (Waiting for cloud response)...", end="", flush=True)

    import threading
    def _heartbeat(stop_event):
        while not stop_event.is_set():
            stop_event.wait(2.0)
            if not stop_event.is_set():
                print(".", end="", flush=True)

    for i, batch in enumerate(batches):
        stop_event = threading.Event()
        hb_thread = threading.Thread(target=_heartbeat, args=(stop_event,))
        hb_thread.start()
            
        try:
            # Pass BOTH glossary_terms (for prompt) and raw_glossary (for validation)
            fixes = ai_provider.review_batch(batch, ai_config, glossary=raw_glossary)
            
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
            
            # Anti-rate-limit sleep between batches (except the last one)
            if i < len(batches) - 1:
                time.sleep(2)
        except Exception as exc:
            logger.error("AI review batch %d failed: %s", i + 1, exc)
        finally:
            stop_event.set()
            hb_thread.join()

    print(" ✅ Response received.")

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

    normalized = [
        normalize_audit_finding(
            _ai_review_to_adapter_shape(r),
            audit_source="ai_review",
            locale="ar",
        )
        for r in normalised
    ]
    return [issue_from_dict(r) for r in normalized]

