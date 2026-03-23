#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
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

def load_issues(runtime):
    """Read existing local audits, prefer final report, else review queue."""
    report_path = runtime.results_dir / "final_audit_report.json"
    if not report_path.exists():
        report_path = runtime.results_dir / "review" / "review_queue.json"
        
    if not report_path.exists():
        return []
        
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("findings", []) + data.get("issues", []) + data.get("review_queue", []) + data.get("rows", [])
    except Exception as e:
        logging.error(f"Failed to load issues from {report_path}: {e}")
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
    for issue in all_issues:
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

    # Build batch
    flawed_keys: dict = {}
    for issue in all_issues:
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
            flawed_keys[k] = {"key": k, "source": src, "current_translation": target, "identified_issue": desc}

    batch_items = list(flawed_keys.values())
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

    # Process in batches using the injected AI provider
    all_fixes: list[dict] = []
    batches = list(chunk_issues(batch_items, batch_size=options.ai_review.batch_size))
    
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
            fixes = ai_provider.review_batch(batch, ai_config)
            all_fixes.extend(fixes)
            
            # Anti-rate-limit sleep between batches (except the last one)
            if i < len(batches) - 1:
                time.sleep(2)
        except Exception as exc:
            logger.error("AI review batch %d failed: %s", i + 1, exc)
        finally:
            stop_event.set()
            hb_thread.join()

    print(" ✅ Response received.")

    if options.write_reports:
        out_dir = options.effective_output_dir(runtime.results_dir) / "per_tool" / "ai_review"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "ai_review_report.json"
        try:
            write_json({"findings": all_fixes}, out_path)
        except Exception as exc:
            logging.warning("Failed to write AI review report: %s", exc)

    normalised = [{**f, "issue_type": "ai_suggestion", "source": "ai_review"} for f in all_fixes]
    return [issue_from_dict(f) for f in normalised]
