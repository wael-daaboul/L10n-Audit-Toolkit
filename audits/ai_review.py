#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import json
import concurrent.futures
from pathlib import Path

from core.audit_runtime import (
    load_locale_mapping,
    load_runtime,
    write_json,
)
from core.workspace import read_json
from ai.provider import request_ai_review
from ai.prompts import get_review_prompt
from ai.verification import verify_batch_fixes

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
