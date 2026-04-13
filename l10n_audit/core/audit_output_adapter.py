"""
audit_output_adapter.py — Phase 7C, Slices 1–3
================================================

Migration-time adapter that normalises the heterogeneous per-audit finding dicts
into a single intermediate shape before they are consumed by ``issue_from_dict``
and the downstream aggregation pipeline.

Contract
--------
This adapter is **transitional**.  Its lifetime ends when all audit modules
complete Phase B (lookup elimination) and emit canonical findings directly.
It must NOT become a permanent second schema system.

Field mapping
-------------

Legacy field          → Normalised field
--------------------  | ------------------
``old``               → ``detected_value``   (value seen at detection time)
``new``               → ``candidate_value``  (suggested replacement, may be "")
``candidate_value``   → ``candidate_value``  (passthrough when already named)
``suggestion``        → ``candidate_value``  (descriptive suggestion fallback)
``audit_source``      → ``audit_source``     (injected if absent)
``locale``            → ``locale``           (injected if absent)

Priority for candidate_value: ``new`` > ``candidate_value`` > ``suggestion``

Intentionally NOT mapped
------------------------
* ``current_value``   — owned exclusively by Stage 3 hydration; never emitted here.
* ``source_old_value`` — canonical field; not touched in this slice.

Non-core fields
---------------
Fields that are not part of the normalised contract surface are preserved verbatim
in ``_raw_metadata`` so that no detection metadata is silently lost.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Fields that are promoted to the top-level normalised shape
# ---------------------------------------------------------------------------
_CORE_FIELDS = frozenset({
    "key",
    "issue_type",
    "severity",
    "message",
    "locale",
    "audit_source",
    "detected_value",
    "candidate_value",
    "fix_mode",
    "related",
})

# Legacy field names that are remapped (removed from top-level, translated).
# 'target' is shimmed to 'old' by ai_review before entering the adapter
# and must not also appear as a top-level passthrough.
_REMAPPED_INPUTS = frozenset({"old", "new", "suggestion", "target"})

# Fields that ``issue_from_dict`` knows about — pass through untouched
_DOWNSTREAM_KNOWN = frozenset({
    "key",
    "issue_type",
    "type",
    "severity",
    "message",
    "description",
    "locale",
    "file",
    "line",
    "suggestion",
    "suggested_fix",
    "approved_new",
    "source",
    # Note: 'target' removed — it is in _REMAPPED_INPUTS (shimmed to 'old' by ai_review)
    # and must land in _raw_metadata, not pass through as a top-level downstream field.
    "current_translation",
    "needs_review",
    "code",
    "decision",
})

# Fields we want at the top-level even though issue_from_dict puts them in extra
_PRESERVE_TOP_LEVEL = frozenset({
    "fix_mode",
    "related",
    "audit_source",
    "detected_value",
    "candidate_value",
    # audit-source-specific annotation fields
    "context_type",
    "ui_surface",
    "text_role",
    "action_hint",
    "audience_hint",
    "context_flags",
    "semantic_risk",
    "lt_signals",
    "review_reason",
    "enforcement_skipped",
})


def normalize_audit_finding(
    row: dict[str, Any],
    *,
    audit_source: str,
    locale: str,
) -> dict[str, Any]:
    """Normalise a single raw audit finding dict into the migration-time shape.

    Parameters
    ----------
    row:
        Raw finding dict as emitted by ``make_finding()`` inside an audit module.
    audit_source:
        Module-level audit source identifier (e.g. ``"en_locale_qc"``).
        Injected when absent from ``row`` or overrides a missing value.
    locale:
        Locale scope of this audit (e.g. ``"en"``, ``"ar"``, ``"en/ar"``).
        Injected when absent from ``row``.

    Returns
    -------
    dict
        Normalised finding dict.  Guaranteed fields: ``key``, ``issue_type``,
        ``severity``, ``message``, ``audit_source``, ``locale``,
        ``detected_value``, ``candidate_value``.
        Non-core fields are preserved in ``_raw_metadata``.
        ``current_value`` is never emitted.
    """
    # --- Core remapping -------------------------------------------------------
    detected_value: str = str(row.get("old") or row.get("detected_value") or "")
    candidate_value: str = str(row.get("new") or row.get("candidate_value") or row.get("suggestion") or "")

    normalised: dict[str, Any] = {
        # --- Identity / classification ----------------------------------------
        "key":             str(row.get("key") or ""),
        "issue_type":      str(row.get("issue_type") or row.get("type") or "unknown"),
        "severity":        str(row.get("severity") or "medium"),
        "message":         str(row.get("message") or row.get("description") or ""),
        # --- Injected context -------------------------------------------------
        "audit_source":    str(row.get("audit_source") or audit_source),
        "locale":          str(row.get("locale") or locale),
        # --- Normalised suggestion fields -------------------------------------
        "detected_value":  detected_value,
        "candidate_value": candidate_value,
        # --- Optional standard fields -----------------------------------------
        "fix_mode":        str(row.get("fix_mode") or "review_required"),
        "related":         str(row.get("related") or ""),
    }

    # --- Pass-through downstream-known fields (code, decision, etc.) ----------
    # Skip fields that were already remapped (old/new/suggestion → detected/candidate_value).
    for field in _DOWNSTREAM_KNOWN:
        if field in row and field not in normalised and field not in _REMAPPED_INPUTS:
            normalised[field] = row[field]

    # --- Preserve annotation metadata fields verbatim -------------------------
    for field in _PRESERVE_TOP_LEVEL:
        if field in row and field not in normalised:
            normalised[field] = row[field]

    # --- Capture remaining unknown fields into _raw_metadata ------------------
    # Capture remaining unknown fields into _raw_metadata.
    # _REMAPPED_INPUTS are intentionally included here: they were consumed into
    # canonical fields (old→detected_value, new/suggestion→candidate_value,
    # target→detected_value) but their original values must also be traceable in
    # _raw_metadata (same pattern as terminology_audit's arabic_value/expected_ar).
    already_placed = (
        _CORE_FIELDS
        | _DOWNSTREAM_KNOWN
        | _PRESERVE_TOP_LEVEL
        | {"description", "type"}
    )
    raw_metadata: dict[str, Any] = {
        k: v for k, v in row.items() if k not in already_placed
    }
    if raw_metadata:
        normalised["_raw_metadata"] = raw_metadata

    # Safety assertion — current_value must never leak from this adapter
    assert "current_value" not in normalised, (
        "audit_output_adapter: 'current_value' must not be emitted — "
        "it is owned by Stage 3 hydration."
    )

    return normalised
