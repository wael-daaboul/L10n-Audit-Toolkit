from __future__ import annotations

import unicodedata

from l10n_audit.core.audit_runtime import compute_text_hash
from l10n_audit.core.source_identity import (
    _CANONICAL_SOURCE_GUARD_DISABLE_FLAG,
    canonical_source_guard_enabled,
    canonicalize_source_identity,
    compute_canonical_source_hash,
)


def test_canonicalize_normalizes_line_endings() -> None:
    assert canonicalize_source_identity("a\r\nb\rc\n") == "a\nb\nc"


def test_canonicalize_normalizes_to_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "Café")
    assert nfd != "Café"
    assert canonicalize_source_identity(nfd) == "Café"


def test_canonicalize_trims_ascii_edges_only() -> None:
    assert canonicalize_source_identity(" \t hello \n") == "hello"


def test_canonicalize_preserves_internal_whitespace() -> None:
    assert canonicalize_source_identity("a   b") == "a   b"


def test_canonicalize_preserves_edge_nbsp() -> None:
    text = "\u00a0hello\u00a0"
    assert canonicalize_source_identity(text) == text


def test_canonicalize_preserves_zero_width_space() -> None:
    text = "\u200bhello\u200b"
    assert canonicalize_source_identity(text) == text


def test_compute_canonical_source_hash_hashes_canonical_value() -> None:
    raw = " Caf" + unicodedata.normalize("NFD", "é") + "\r\n"
    canonical = canonicalize_source_identity(raw)
    assert canonical == "Café"
    assert compute_canonical_source_hash(raw) == compute_text_hash(canonical)


def test_canonical_source_guard_enabled_by_default(monkeypatch) -> None:
    # Phase 1 Completion: guard is ON by default — no env var needed.
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)
    assert canonical_source_guard_enabled() is True


def test_canonical_source_guard_disabled_by_disable_flag(monkeypatch) -> None:
    # Escape hatch: set DISABLE flag to turn guard off for debugging.
    monkeypatch.setenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, "1")
    assert canonical_source_guard_enabled() is False


def test_canonical_source_guard_flag_enabled_truthy(monkeypatch) -> None:
    # Old enable flag no longer controls the guard; guard is on by default.
    # Confirm it doesn't accidentally disable the guard when the old var is set.
    monkeypatch.setenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", "1")
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)
    assert canonical_source_guard_enabled() is True
