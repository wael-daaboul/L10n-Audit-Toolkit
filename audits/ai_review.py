#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import logging
import os
import re
from pathlib import Path
from core.audit_runtime import (
    load_locale_mapping,
    load_runtime,
    write_json,
)
from ai.provider import request_ai_review
from ai.prompts import get_review_prompt
from ai.verification import check_placeholders, check_newlines, check_html

def should_skip(key, source, target):
    """
    Implements the 5 pre-filtering rules:
    1. Short texts (OK, Cancel)
    2. ICU patterns {count, plural, ...}
    3. Very long texts (> 300 chars)
    4. Numeric/Placeholder only texts
    5. Technical/Non-sentence texts
    """
    if not source or not target:
        return True
    
    # 1. Short texts
    if len(source) < 3 or len(target) < 3:
        return True
    
    # 2. ICU patterns
    if "{" in source and ("plural" in source or "select" in source or "ordinal" in source):
        return True
        
    # 3. Long texts
    if len(source) > 300:
        return True
        
    # 4. Numeric/Placeholder only
    # If stripping placeholders and numbers leaves nothing significant
    stripped = re.sub(r"\{[^}]+\}|%(\([^)]+\))?[-#0 +]*[\d\.]*[hlL]*[diouxXeEfFgGcrs%]|[\d\W_]+", "", source).strip()
    if not stripped:
        return True
        
    return False

def main() -> None:
    runtime = load_runtime(__file__, validate=False)
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-enabled", action="store_true", help="Enable AI review")
    parser.add_argument("--ai-api-key", help="API Key (or use env)")
    parser.add_argument("--ai-api-base", help="API Base URL")
    parser.add_argument("--ai-model", help="AI Model name")
    parser.add_argument("--out-json", help="Output JSON path")
    
    # Standard L10n Audit flags
    parser.add_argument("--en", default=str(runtime.en_file))
    parser.add_argument("--ar", default=str(runtime.ar_file))
    
    args, unknown = parser.parse_known_args()

    if not args.ai_enabled:
        print("AI Review is disabled. Use --ai-enabled to run.")
        return

    # Configuration
    config = {
        "api_key": args.ai_api_key or os.getenv(os.getenv("AI_API_KEY_ENV", "OPENAI_API_KEY")),
        "api_base": args.ai_api_base or os.getenv("AI_API_BASE", "https://api.openai.com/v1"),
        "model": args.ai_model or os.getenv("AI_API_MODEL", "gpt-4o-mini")
    }

    if not config["api_key"]:
        print("Error: AI API Key not found. Set OPENAI_API_KEY or use --ai-api-key")
        return

    en_data = load_locale_mapping(Path(args.en), runtime, "en")
    ar_data = load_locale_mapping(Path(args.ar), runtime, "ar")

    findings = []
    keys = sorted(set(en_data) & set(ar_data))
    
    print(f"Starting AI Review for {len(keys)} keys...")

    for key in keys:
        source = en_data[key]
        target = ar_data[key]
        
        if not isinstance(source, str) or not isinstance(target, str):
            continue
            
        if should_skip(key, source, target):
            continue
            
        print(f"  Reviewing: {key}...", end="\r")
        
        prompt = get_review_prompt(source, target)
        result = request_ai_review(prompt, config)
        
        if result and "suggestion" in result:
            suggestion = result["suggestion"]
            reason = result.get("reason", "")
            
            # If suggestion is identical, skip
            if suggestion.strip() == target.strip():
                continue
                
            # Verification
            v_tasks = [
                check_placeholders(source, suggestion),
                check_newlines(source, suggestion),
                check_html(source, suggestion)
            ]
            
            failed = [msg for ok, msg in v_tasks if not ok]
            
            if not failed:
                findings.append({
                    "key": key,
                    "issue_type": "ai_suggestion",
                    "severity": "info",
                    "message": f"AI Suggestion: {reason}",
                    "source": source,
                    "target": target,
                    "suggestion": suggestion
                })
            else:
                logging.debug(f"AI Suggestion for {key} rejected by verification: {failed}")

    out_path = args.out_json or str(runtime.results_dir / "ai_review_report.json")
    write_json({"findings": findings}, Path(out_path))
    
    print(f"\nDone. AI suggestions found: {len(findings)}")
    print(f"Report saved to: {out_path}")

if __name__ == "__main__":
    main()
