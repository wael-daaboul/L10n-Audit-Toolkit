from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.core.source_hash_diagnostics import emit_source_hash_probe
from l10n_audit.fixes.apply_review_fixes import run_apply
from l10n_audit.fixes.fix_merger import FROZEN_ARTIFACT_TYPE_VALUE, prepare_apply_workbook
from l10n_audit.reports.report_aggregator import build_review_queue


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def test_diagnostics_disabled_emits_nothing(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "diag"
    monkeypatch.delenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", raising=False)
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))

    emit_source_hash_probe(
        phase="run_review_queue_build",
        carrier="hydration.current_value",
        key="welcome",
        locale="ar",
        value="1 من ",
    )

    assert not (out_dir / "run_review_queue_build.jsonl").exists()


def test_run_build_emits_source_hash_diagnostics(tmp_path: Path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))

    issues = [
        {
            "key": "welcome",
            "locale": "ar",
            "issue_type": "grammar",
            "severity": "low",
            "source": "manual",
            "message": "needs update",
            "candidate_value": "مرحبا",
        }
    ]
    rows = build_review_queue(issues, runtime)
    assert len(rows) == 1

    log_path = out_dir / "run_review_queue_build.jsonl"
    assert log_path.exists()
    events = _read_jsonl(log_path)
    assert events
    event = events[-1]
    assert event["phase"] == "run_review_queue_build"
    assert event["carrier"] == "hydration.current_value"
    assert event["key"] == "welcome"
    assert event["locale"] == "ar"
    assert event["raw_text"] == "اهلا"
    assert event["computed_hash"] == compute_text_hash("اهلا")
    assert event["canonical_text"] == "اهلا"
    assert event["canonical_computed_hash"] == compute_text_hash("اهلا")
    assert event["stored_source_hash"] == compute_text_hash("اهلا")
    assert event["actual_source_hash"] == compute_text_hash("اهلا")
    assert event["hash_match"] is True


def test_prepare_apply_emits_source_hash_diagnostics(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))

    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    rows = [
        {
            "key": "welcome",
            "locale": "ar",
            "issue_type": "grammar",
            "current_value": "1 من ",
            "candidate_value": "مرحبا",
            "approved_new": "",
            "status": "approved",
            "review_note": "ok",
            "source_old_value": "1 من ",
            "source_hash": compute_text_hash("1 من "),
            "suggested_hash": compute_text_hash("مرحبا"),
            "plan_id": "plan-1",
            "generated_at": "2026-04-08T00:00:00+00:00",
        }
    ]
    columns = [
        "key",
        "locale",
        "issue_type",
        "current_value",
        "candidate_value",
        "approved_new",
        "status",
        "review_note",
        "source_old_value",
        "source_hash",
        "suggested_hash",
        "plan_id",
        "generated_at",
    ]
    write_simple_xlsx(rows, columns, queue, sheet_name="Review Queue")

    payload = prepare_apply_workbook(queue, final, report)
    assert payload["summary"]["accepted_rows"] == 1

    log_path = out_dir / "prepare_apply.jsonl"
    assert log_path.exists()
    events = _read_jsonl(log_path)
    assert events
    event = events[-1]
    assert event["phase"] == "prepare_apply"
    assert event["carrier"] == "workbook.current_value"
    assert event["key"] == "welcome"
    assert event["locale"] == "ar"
    assert event["plan_id"] == "plan-1"
    assert event["raw_text"] == "1 من "
    assert event["computed_hash"] == compute_text_hash("1 من ")
    assert event["canonical_text"] == "1 من"
    assert event["canonical_computed_hash"] == compute_text_hash("1 من")
    assert event["stored_source_hash"] == compute_text_hash("1 من ")
    assert event["actual_source_hash"] == compute_text_hash("1 من ")
    assert event["hash_match"] is True


def test_apply_emits_source_hash_diagnostics(tmp_path: Path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))

    review_queue = runtime.results_dir / "review" / "review_final.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "approved_new": "مرحبا",
                "status": "approved",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-03-08T00:00:00+00:00",
                "current_value": "اهلا",
                "candidate_value": "مرحبا",
                "frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE,
            }
        ],
        [
            "key",
            "locale",
            "issue_type",
            "approved_new",
            "status",
            "source_old_value",
            "source_hash",
            "suggested_hash",
            "plan_id",
            "generated_at",
            "current_value",
            "candidate_value",
            "frozen_artifact_type",
        ],
        review_queue,
        sheet_name="Review Final",
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))
    assert report["summary"]["approved_rows_applied"] == 1

    log_path = out_dir / "apply.jsonl"
    assert log_path.exists()
    events = _read_jsonl(log_path)
    assert events
    event = events[-1]
    assert event["phase"] == "apply"
    assert event["carrier"] == "runtime.live_value"
    assert event["key"] == "welcome"
    assert event["locale"] == "ar"
    assert event["plan_id"] == "plan-1"
    assert event["raw_text"] == "اهلا"
    assert event["computed_hash"] == compute_text_hash("اهلا")
    assert event["canonical_text"] == "اهلا"
    assert event["canonical_computed_hash"] == compute_text_hash("اهلا")
    assert event["stored_source_hash"] == compute_text_hash("اهلا")
    assert event["actual_source_hash"] == compute_text_hash("اهلا")
    assert event["hash_match"] is True


def test_prepare_apply_guard_on_emits_raw_and_canonical_compare_fields(tmp_path: Path, monkeypatch) -> None:
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.setenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", "1")

    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    rows = [
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
            "source_hash": compute_text_hash(" 1 من "),
            "suggested_hash": compute_text_hash("مرحبا"),
            "plan_id": "plan-1",
            "generated_at": "2026-04-08T00:00:00+00:00",
        }
    ]
    columns = [
        "key",
        "locale",
        "issue_type",
        "current_value",
        "candidate_value",
        "approved_new",
        "status",
        "review_note",
        "source_old_value",
        "source_hash",
        "suggested_hash",
        "plan_id",
        "generated_at",
    ]
    write_simple_xlsx(rows, columns, queue, sheet_name="Review Queue")

    payload = prepare_apply_workbook(queue, final, report)
    assert payload["summary"]["accepted_rows"] == 1

    log_path = out_dir / "prepare_apply.jsonl"
    events = _read_jsonl(log_path)
    event = events[-1]
    assert event["hash_match"] is False
    assert event["canonical_hash_match"] is True
    assert event["source_guard_mode"] == "canonical"
    assert event["authoritative_hash_kind"] == "canonical"
    assert event["authoritative_hash_match"] is True
    assert event["canonical_stored_source_hash"] == compute_text_hash("1 من")
    assert event["canonical_actual_source_hash"] == compute_text_hash("1 من")


def test_apply_guard_on_emits_raw_and_canonical_compare_fields(tmp_path: Path, monkeypatch) -> None:
    runtime = _make_runtime(tmp_path)
    _write_json(runtime.ar_file, {"welcome": "Cafe\u0301"})
    out_dir = tmp_path / "diag"
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS", "1")
    monkeypatch.setenv("L10N_AUDIT_SOURCE_HASH_DIAGNOSTICS_DIR", str(out_dir))
    monkeypatch.setenv("L10N_AUDIT_CANONICAL_SOURCE_GUARD", "1")

    review_queue = runtime.results_dir / "review" / "review_final.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "approved_new": "مرحبا",
                "status": "approved",
                "source_old_value": "Café",
                "source_hash": compute_text_hash("Café"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-03-08T00:00:00+00:00",
                "current_value": "Café",
                "candidate_value": "مرحبا",
                "frozen_artifact_type": FROZEN_ARTIFACT_TYPE_VALUE,
            }
        ],
        [
            "key",
            "locale",
            "issue_type",
            "approved_new",
            "status",
            "source_old_value",
            "source_hash",
            "suggested_hash",
            "plan_id",
            "generated_at",
            "current_value",
            "candidate_value",
            "frozen_artifact_type",
        ],
        review_queue,
        sheet_name="Review Final",
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))
    assert report["summary"]["approved_rows_applied"] == 1

    log_path = out_dir / "apply.jsonl"
    events = _read_jsonl(log_path)
    event = events[-1]
    assert event["hash_match"] is False
    assert event["canonical_hash_match"] is True
    assert event["source_guard_mode"] == "canonical"
    assert event["authoritative_hash_kind"] == "canonical"
    assert event["authoritative_hash_match"] is True
    assert event["canonical_stored_source_hash"] == compute_text_hash("Café")
    assert event["canonical_actual_source_hash"] == compute_text_hash("Café")
