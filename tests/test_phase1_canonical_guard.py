"""Phase 1 Completion — Canonical Guard Stabilization regression tests.

Covers:
* canonical guard is ON by default (no env var needed)
* disable flag turns the guard OFF for debugging
* divergence_detected field present in compare events
* previously false-rejected cases (LF/CRLF, NFD/NFC, edge-whitespace) now
  accepted by default without any flag
* true semantic mutations remain rejected even with canonical guard on
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.core.source_identity import (
    _CANONICAL_SOURCE_GUARD_DISABLE_FLAG,
    canonical_source_guard_enabled,
)
from l10n_audit.fixes.apply_review_fixes import run_apply
from l10n_audit.fixes.fix_merger import FROZEN_ARTIFACT_TYPE_VALUE, prepare_apply_workbook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _make_runtime(tmp_path: Path) -> SimpleNamespace:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    _write_json(en_file, {"welcome": "Welcome"})
    _write_json(ar_file, {"welcome": "اهلا"})
    return SimpleNamespace(
        project_root=tmp_path,
        results_dir=tmp_path / "Results",
        en_file=en_file,
        ar_file=ar_file,
        original_en_file=en_file,
        original_ar_file=ar_file,
        locale_format="json",
        source_locale="en",
        target_locales=("ar",),
        metadata={},
    )


def _make_review_final(
    tmp_path: Path,
    *,
    source_old_value: str,
    source_hash: str,
    current_value: str | None = None,
) -> Path:
    """Write a minimal review_final.xlsx for run_apply."""
    path = tmp_path / "Results" / "review" / "review_final.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    current_value = current_value if current_value is not None else source_old_value
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "approved_new": "مرحبا",
                "status": "approved",
                "source_old_value": source_old_value,
                "source_hash": source_hash,
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-04-01T00:00:00+00:00",
                "current_value": current_value,
                "candidate_value": "مرحبا",
                "frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE,
            }
        ],
        [
            "key", "locale", "issue_type", "approved_new", "status",
            "source_old_value", "source_hash", "suggested_hash", "plan_id",
            "generated_at", "current_value", "candidate_value", "frozen_artifact_type",
        ],
        path,
        sheet_name="Review Final",
    )
    return path


# ---------------------------------------------------------------------------
# 1. canonical_source_guard_enabled() default-on
# ---------------------------------------------------------------------------


def test_canonical_guard_enabled_by_default_no_env_vars(monkeypatch) -> None:
    """Guard must be ON with no env vars set."""
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)
    assert canonical_source_guard_enabled() is True


def test_canonical_guard_disabled_by_disable_flag(monkeypatch) -> None:
    """Setting the disable flag turns the guard OFF."""
    monkeypatch.setenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, "1")
    assert canonical_source_guard_enabled() is False


def test_canonical_guard_disable_flag_truthy_variants(monkeypatch) -> None:
    for value in ("true", "yes", "on", "1"):
        monkeypatch.setenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, value)
        assert canonical_source_guard_enabled() is False, f"Expected False for disable={value!r}"


def test_canonical_guard_disable_flag_falsy_leaves_guard_on(monkeypatch) -> None:
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, value)
        assert canonical_source_guard_enabled() is True, f"Expected True for disable={value!r}"


# ---------------------------------------------------------------------------
# 2. False-rejection regression — cases now accepted by default
# ---------------------------------------------------------------------------


def test_apply_default_on_accepts_crlf_drift(tmp_path: Path, monkeypatch) -> None:
    """CRLF-vs-LF drift: accepted by default (no flags needed)."""
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    runtime = _make_runtime(tmp_path)
    # Runtime file has CRLF; plan recorded LF
    _write_json(runtime.ar_file, {"welcome": "line1\r\nline2"})
    path = _make_review_final(
        tmp_path,
        source_old_value="line1\nline2",
        source_hash=compute_text_hash("line1\nline2"),
    )

    report = run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 1, (
        "CRLF drift should be auto-accepted when canonical guard is on by default"
    )


def test_apply_default_on_accepts_nfc_nfd_drift(tmp_path: Path, monkeypatch) -> None:
    """NFD-vs-NFC drift: accepted by default (no flags needed)."""
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    runtime = _make_runtime(tmp_path)
    nfc = "Café"
    nfd = "Cafe\u0301"
    # Runtime file has NFD; plan recorded NFC
    _write_json(runtime.ar_file, {"welcome": nfd})
    path = _make_review_final(
        tmp_path,
        source_old_value=nfc,
        source_hash=compute_text_hash(nfc),
    )

    report = run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 1, (
        "NFD/NFC drift should be auto-accepted when canonical guard is on by default"
    )


def test_prepare_apply_default_on_accepts_edge_whitespace_drift(tmp_path: Path, monkeypatch) -> None:
    """Edge-whitespace drift in source_hash: accepted by default (no flags needed)."""
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "grammar",
                "current_value": "1 من",
                "candidate_value": "مرحبا",
                "approved_new": "مرحبا",
                "status": "approved",
                "review_note": "ok",
                "source_old_value": "1 من",
                # source_hash computed from padded value — simulates plan-time whitespace
                "source_hash": compute_text_hash(" 1 من "),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-04-01T00:00:00+00:00",
            }
        ],
        [
            "key", "locale", "issue_type", "current_value", "candidate_value",
            "approved_new", "status", "review_note", "source_old_value",
            "source_hash", "suggested_hash", "plan_id", "generated_at",
        ],
        queue,
        sheet_name="Review Queue",
    )

    payload = prepare_apply_workbook(queue, final, report)

    assert payload["summary"]["accepted_rows"] == 1, (
        "Edge-whitespace drift should be auto-accepted when canonical guard is on by default"
    )


# ---------------------------------------------------------------------------
# 3. True semantic mutations still rejected with canonical guard on
# ---------------------------------------------------------------------------


def test_apply_default_on_rejects_true_semantic_mutation(tmp_path: Path, monkeypatch) -> None:
    """Different semantic text must still be rejected even when guard is on."""
    monkeypatch.delenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", raising=False)
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    runtime = _make_runtime(tmp_path)
    # Runtime has truly different text (not just encoding drift)
    _write_json(runtime.ar_file, {"welcome": "نص مختلف تماماً"})
    path = _make_review_final(
        tmp_path,
        source_old_value="اهلا",
        source_hash=compute_text_hash("اهلا"),
        current_value="اهلا",
    )

    report = run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "source_hash_mismatch"


# ---------------------------------------------------------------------------
# 4. Disable-flag puts guard back in raw mode (escape hatch behavior)
# ---------------------------------------------------------------------------


def test_apply_disable_flag_rejects_crlf_drift(tmp_path: Path, monkeypatch) -> None:
    """With guard disabled, CRLF drift causes source_hash_mismatch (expected raw-mode behavior)."""
    monkeypatch.setenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, "1")

    runtime = _make_runtime(tmp_path)
    _write_json(runtime.ar_file, {"welcome": "line1\r\nline2"})
    path = _make_review_final(
        tmp_path,
        source_old_value="line1\nline2",
        source_hash=compute_text_hash("line1\nline2"),
    )

    report = run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "source_hash_mismatch"


# ---------------------------------------------------------------------------
# 5. Divergence telemetry — divergence_detected field
# ---------------------------------------------------------------------------


def test_divergence_detected_false_when_no_encoding_drift(tmp_path: Path, monkeypatch) -> None:
    """divergence_detected=False when raw value already matches its canonical form."""
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    runtime = _make_runtime(tmp_path)
    path = _make_review_final(
        tmp_path,
        source_old_value="اهلا",
        source_hash=compute_text_hash("اهلا"),
    )

    run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    events = _read_jsonl(out_dir / "apply.jsonl")
    compare_events = [e for e in events if e.get("event_type") == "compare"]
    assert compare_events, "Expected at least one compare event"
    event = compare_events[-1]
    assert "divergence_detected" in event
    assert event["divergence_detected"] is False


def test_divergence_detected_true_for_crlf_drift(tmp_path: Path, monkeypatch) -> None:
    """divergence_detected=True when the runtime value contains CRLF (encoding drift)."""
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    runtime = _make_runtime(tmp_path)
    # Runtime file has CRLF — this value diverges from its canonical form
    _write_json(runtime.ar_file, {"welcome": "line1\r\nline2"})
    path = _make_review_final(
        tmp_path,
        source_old_value="line1\nline2",
        source_hash=compute_text_hash("line1\nline2"),
    )

    run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    events = _read_jsonl(out_dir / "apply.jsonl")
    compare_events = [e for e in events if e.get("event_type") == "compare"]
    assert compare_events, "Expected at least one compare event"
    event = compare_events[-1]
    assert "divergence_detected" in event
    assert event["divergence_detected"] is True, (
        "CRLF runtime value must trigger divergence_detected=True"
    )


def test_divergence_detected_true_for_nfd_value(tmp_path: Path, monkeypatch) -> None:
    """divergence_detected=True when the runtime value is in NFD form."""
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    nfc = "Café"
    nfd = "Cafe\u0301"

    runtime = _make_runtime(tmp_path)
    _write_json(runtime.ar_file, {"welcome": nfd})
    path = _make_review_final(
        tmp_path,
        source_old_value=nfc,
        source_hash=compute_text_hash(nfc),
    )

    run_apply(runtime, path, out_final_json=str(runtime.results_dir / "final.json"))

    events = _read_jsonl(out_dir / "apply.jsonl")
    compare_events = [e for e in events if e.get("event_type") == "compare"]
    assert compare_events, "Expected at least one compare event"
    event = compare_events[-1]
    assert "divergence_detected" in event
    assert event["divergence_detected"] is True, (
        "NFD runtime value must trigger divergence_detected=True"
    )


def test_divergence_detected_in_prepare_apply_events(tmp_path: Path, monkeypatch) -> None:
    """divergence_detected also present in prepare_apply compare events."""
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.delenv(_CANONICAL_SOURCE_GUARD_DISABLE_FLAG, raising=False)

    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    # Edge-whitespace value — diverges from canonical
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "grammar",
                "current_value": "1 من ",
                "candidate_value": "مرحبا",
                "approved_new": "مرحبا",
                "status": "approved",
                "review_note": "ok",
                "source_old_value": "1 من ",
                "source_hash": compute_text_hash("1 من "),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-04-01T00:00:00+00:00",
            }
        ],
        [
            "key", "locale", "issue_type", "current_value", "candidate_value",
            "approved_new", "status", "review_note", "source_old_value",
            "source_hash", "suggested_hash", "plan_id", "generated_at",
        ],
        queue,
        sheet_name="Review Queue",
    )

    prepare_apply_workbook(queue, final, report)

    events = _read_jsonl(out_dir / "prepare_apply.jsonl")
    compare_events = [e for e in events if e.get("event_type") == "compare"]
    assert compare_events
    event = compare_events[-1]
    assert "divergence_detected" in event
    # "1 من " has trailing space — diverges from canonical "1 من"
    assert event["divergence_detected"] is True
