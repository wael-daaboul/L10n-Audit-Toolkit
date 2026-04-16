from __future__ import annotations

import os
import unicodedata

from l10n_audit.core.audit_runtime import compute_text_hash

# v1: Keep edge trimming narrow to preserve NBSP and zero-width chars.
_EDGE_TRIMMABLE_CHARS: frozenset[str] = frozenset({" ", "\t", "\n", "\r", "\f", "\v"})
_CANONICAL_SOURCE_GUARD_FLAG = "L10N_AUDIT_CANONICAL_SOURCE_GUARD"
_TRUTHY = {"1", "true", "yes", "on"}


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _trim_v1_edges(text: str) -> str:
    start = 0
    end = len(text)
    while start < end and text[start] in _EDGE_TRIMMABLE_CHARS:
        start += 1
    while end > start and text[end - 1] in _EDGE_TRIMMABLE_CHARS:
        end -= 1
    return text[start:end]


def canonicalize_source_identity(text: str) -> str:
    normalized = _normalize_line_endings(text)
    normalized = unicodedata.normalize("NFC", normalized)
    normalized = _trim_v1_edges(normalized)
    return normalized


def compute_canonical_source_hash(text: str) -> str:
    return compute_text_hash(canonicalize_source_identity(text))


def canonical_source_guard_enabled() -> bool:
    raw = str(os.environ.get(_CANONICAL_SOURCE_GUARD_FLAG, "")).strip().lower()
    return raw in _TRUTHY
