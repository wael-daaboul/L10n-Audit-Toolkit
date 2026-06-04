"""
Standalone CAMeL Validation Stage.
Analyzes target Arabic translations using CAMeL Tools or the pure-Python fallback.
"""

from __future__ import annotations

import logging
from l10n_audit.models import AuditIssue, issue_from_dict
from l10n_audit.core.audit_output_adapter import normalize_audit_finding
from l10n_audit.core.arabic_nlp_layer import analyze_arabic_text
from l10n_audit.core.audit_runtime import load_locale_mapping

logger = logging.getLogger("l10n_audit.camel_validation")

def run_stage(runtime, options, en_data: dict | None = None, ar_data: dict | None = None) -> list[AuditIssue]:
    # Phase B: load canonical state if not pre-injected
    if ar_data is None:
        logger.warning("camel_validation invoked without paired canonical state. Falling back to internal lookup.")
        ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")

    rows = []
    
    cfg = getattr(runtime, "config", None) or {}
    enable_dialect = False
    arabic_nlp = cfg.get("arabic_nlp")
    if isinstance(arabic_nlp, dict):
        enable_dialect = bool(arabic_nlp.get("enable_dialect", False))
        
    for key, value in ar_data.items():
        if not isinstance(value, str) or not value.strip():
            continue
            
        analysis = analyze_arabic_text(value, enable_dialect=enable_dialect)
        
        # 1. Unknown tokens check
        unknown_count = analysis.get("camel_unknown_count")
        if unknown_count and unknown_count.isdigit() and int(unknown_count) > 0:
            unknown_tokens = analysis.get("camel_unknown_tokens", "")
            rows.append({
                "key": key,
                "issue_type": "camel_unknown_token",
                "severity": "info",
                "message": f"Arabic translation contains unknown/unrecognized tokens: {unknown_tokens}",
                "old": value,
                "new": "",
                "fix_mode": "review_required",
                "extra": analysis,
            })
            
        # 2. Mixed script check
        if analysis.get("camel_mixed_script") == "yes":
            rows.append({
                "key": key,
                "issue_type": "camel_mixed_script",
                "severity": "info",
                "message": "Arabic translation contains mixed script (Arabic and Latin characters mixed)",
                "old": value,
                "new": "",
                "fix_mode": "review_required",
                "extra": analysis,
            })
            
    logger.info("CAMeL Validation stage: found %d issues.", len(rows))
    
    if options.write_reports:
        from collections import Counter
        from l10n_audit.core.audit_runtime import write_json
        results_dir = options.effective_output_dir(runtime.results_dir)
        out_dir = results_dir / ".cache" / "raw_tools" / "camel_validation"
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": {
                "keys_scanned": len(ar_data),
                "findings": len(rows),
                "issue_types": dict(Counter(r["issue_type"] for r in rows)),
            },
            "findings": rows,
        }
        try:
            write_json(payload, out_dir / "camel_validation_report.json")
        except Exception as exc:
            logger.warning("Failed to write CAMeL validation raw report: %s", exc)

    normalised = []
    for r in rows:
        norm = normalize_audit_finding(r, audit_source="camel_validation", locale="ar")
        normalised.append(issue_from_dict(norm))
        
    return normalised
