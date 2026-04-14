"""
Minimal audit to prove extensibility and boundary compliance.
Detects identical EN and AR translations, reading purely from injected canonical state.
"""

from __future__ import annotations

import logging
from l10n_audit.models import AuditIssue, issue_from_dict
from l10n_audit.core.audit_output_adapter import normalize_audit_finding

logger = logging.getLogger("l10n_audit.basic_consistency")

def run_stage(runtime, options, en_data: dict | None = None, ar_data: dict | None = None) -> list[AuditIssue]:
    en_data = en_data or {}
    ar_data = ar_data or {}
    
    rows = []
    
    for key, en_text in en_data.items():
        ar_text = ar_data.get(key)
        
        # Skip if missing or explicitly empty (empty string issues are caught elsewhere)
        if not isinstance(en_text, str) or not isinstance(ar_text, str) or not en_text.strip() or not ar_text.strip():
            continue
            
        # Basic check: is the Arabic text exactly the same as English?
        # (Usually implies a missing translation where English was copy-pasted)
        if en_text == ar_text and any(c.isalpha() for c in en_text):
            rows.append({
                "key": key,
                "issue_type": "identical_translation",
                "severity": "medium",
                "message": "Arabic translation is exactly identical to the English source (possible missing translation).",
                "old": ar_text,  # AR value at detection time
                "new": "",       # We don't have an auto-fix for missing translation
                "fix_mode": "review_required"
            })
            
    logger.info("Basic consistency check: found %d identical translations.", len(rows))
    
    # Prove the adapter pipeline integration: normalize and convert structure
    normalised = []
    for r in rows:
        norm = normalize_audit_finding(r, audit_source="basic_consistency", locale="ar")
        normalised.append(issue_from_dict(norm))
        
    return normalised
