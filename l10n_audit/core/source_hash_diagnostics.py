from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from l10n_audit.core.audit_runtime import compute_text_hash
from l10n_audit.core.source_identity import canonicalize_source_identity, compute_canonical_source_hash

logger = logging.getLogger("l10n_audit.source_hash_diagnostics")

_FLAG_NAME = "L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS"
_DIR_OVERRIDE_NAME = "L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR"
_TRUTHY = {"1", "true", "yes", "on"}


def diagnostics_enabled() -> bool:
    raw = str(os.environ.get(_FLAG_NAME, "")).strip().lower()
    return raw in _TRUTHY


def _resolve_output_dir(*, results_dir: Path | None) -> Path:
    override = os.environ.get(_DIR_OVERRIDE_NAME)
    if override:
        return Path(override).expanduser()
    if results_dir is not None:
        return results_dir / ".cache" / "source_hash_diagnostics"
    return Path("Results") / ".cache" / "source_hash_diagnostics"


def _codepoints(text: str) -> list[str]:
    return [f"U+{ord(ch):04X}" for ch in text]


def _normalize_text(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def _build_text_probe_payload(
    *,
    phase: str,
    carrier: str,
    key: str,
    locale: str,
    value: object,
    plan_id: str | None = None,
    row_index: int | None = None,
) -> dict[str, Any]:
    text = _normalize_text(value)
    canonical_text = canonicalize_source_identity(text)
    payload: dict[str, Any] = {
        "event_type": "probe",
        "phase": phase,
        "carrier": carrier,
        "key": key,
        "locale": locale,
        "plan_id": plan_id if plan_id else "",
        "row_index": row_index,
        "raw_text": text,
        "debug_repr": repr(text),
        "text_length": len(text),
        "codepoints": _codepoints(text),
        "computed_hash": compute_text_hash(text),
        "canonicalization_profile": "v1_line_endings_nfc_trim_edges",
        "canonical_text": canonical_text,
        "canonical_debug_repr": repr(canonical_text),
        "canonical_text_length": len(canonical_text),
        "canonical_codepoints": _codepoints(canonical_text),
        "canonical_computed_hash": compute_canonical_source_hash(text),
    }
    return payload


def _emit(payload: dict[str, Any], *, phase: str, results_dir: Path | None) -> None:
    if not diagnostics_enabled():
        return
    try:
        out_dir = _resolve_output_dir(results_dir=results_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{phase}.jsonl"
        with out_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception:
        # Diagnostics must never affect workflow behavior.
        logger.debug("Source hash diagnostics emission failed", exc_info=True)


def emit_source_hash_probe(
    *,
    phase: str,
    carrier: str,
    key: str,
    locale: str,
    value: object,
    plan_id: str | None = None,
    row_index: int | None = None,
    results_dir: Path | None = None,
) -> None:
    payload = _build_text_probe_payload(
        phase=phase,
        carrier=carrier,
        key=key,
        locale=locale,
        value=value,
        plan_id=plan_id,
        row_index=row_index,
    )
    _emit(payload, phase=phase, results_dir=results_dir)


def emit_source_hash_compare(
    *,
    phase: str,
    carrier: str,
    key: str,
    locale: str,
    value: object,
    stored_source_hash: str,
    actual_source_hash: str,
    canonical_stored_source_hash: str | None = None,
    canonical_actual_source_hash: str | None = None,
    canonical_hash_match: bool | None = None,
    source_guard_mode: str | None = None,
    authoritative_hash_kind: str | None = None,
    authoritative_hash_match: bool | None = None,
    plan_id: str | None = None,
    row_index: int | None = None,
    results_dir: Path | None = None,
) -> None:
    payload = _build_text_probe_payload(
        phase=phase,
        carrier=carrier,
        key=key,
        locale=locale,
        value=value,
        plan_id=plan_id,
        row_index=row_index,
    )
    payload.update(
        {
            "event_type": "compare",
            "stored_source_hash": stored_source_hash,
            "actual_source_hash": actual_source_hash,
            "hash_match": stored_source_hash == actual_source_hash,
            # Phase 1 Completion: divergence_detected flags when the raw value hash
            # differs from its canonical hash.  This means the value contains
            # whitespace / encoding variants that canonicalize differently.
            # True  → canonical guard matters for this value (encoding drift present)
            # False → raw and canonical are identical (no encoding drift)
            "divergence_detected": payload["computed_hash"] != payload["canonical_computed_hash"],
        }
    )
    if canonical_stored_source_hash is not None:
        payload["canonical_stored_source_hash"] = canonical_stored_source_hash
    if canonical_actual_source_hash is not None:
        payload["canonical_actual_source_hash"] = canonical_actual_source_hash
    if canonical_hash_match is not None:
        payload["canonical_hash_match"] = canonical_hash_match
    if source_guard_mode is not None:
        payload["source_guard_mode"] = source_guard_mode
    if authoritative_hash_kind is not None:
        payload["authoritative_hash_kind"] = authoritative_hash_kind
    if authoritative_hash_match is not None:
        payload["authoritative_hash_match"] = authoritative_hash_match
    _emit(payload, phase=phase, results_dir=results_dir)
