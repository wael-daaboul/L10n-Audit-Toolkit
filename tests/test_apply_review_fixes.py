import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from l10n_audit.core.audit_runtime import AuditRuntimeError, compute_text_hash, write_simple_xlsx
from l10n_audit.fixes.apply_review_fixes import run_apply


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_runtime(tmp_path: Path) -> SimpleNamespace:
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    _write_json(en_file, {"welcome": "Welcome", "keep": "Keep"})
    _write_json(ar_file, {"welcome": "اهلا", "keep": "كما هو"})
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


def _review_row(**overrides: object) -> dict[str, object]:
    base = {
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
    }
    base.update(overrides)
    return base


def _write_review_queue(path: Path, rows: list[dict[str, object]]) -> None:
    write_simple_xlsx(
        rows,
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
        ],
        path,
        sheet_name="Review Queue",
    )


def test_apply_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row(source_hash=compute_text_hash("قيمة قديمة"))])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "source_hash_mismatch"
    assert runtime.metadata["apply_rejections"][0]["reason"] == "source_hash_mismatch"


def test_apply_rejects_tampered_approved_new(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row(approved_new="تم تحريرها يدويًا")])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "tampered_row_detected"
    assert runtime.metadata["apply_rejections"][0]["reason"] == "tampered_row_detected"


def test_apply_rejects_missing_required_fields(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row(current_value="", candidate_value="")])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "missing_required_fields"
    assert set(report["skipped"][0]["missing_fields"]) == {"current_value", "candidate_value"}


def test_apply_rejects_missing_approved_new_even_when_candidate_value_exists(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    final_workbook = runtime.results_dir / "review" / "review_final.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "status": "approved",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-03-08T00:00:00+00:00",
                "current_value": "اهلا",
                "candidate_value": "مرحبا",
            }
        ],
        [
            "key", "locale", "issue_type", "status", "source_old_value",
            "source_hash", "suggested_hash", "plan_id", "generated_at",
            "current_value", "candidate_value",
        ],
        final_workbook,
        sheet_name="Review Final",
    )

    with pytest.raises(AuditRuntimeError):
        run_apply(runtime, final_workbook, out_final_json=str(runtime.results_dir / "final.json"))


def test_apply_rejects_queue_shaped_workbook_without_fallback(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    queue_like = runtime.results_dir / "review" / "review_final.xlsx"
    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "current_value": "اهلا",
                "candidate_value": "مرحبا",
                "status": "approved",
                "review_note": "",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-03-08T00:00:00+00:00",
            }
        ],
        [
            "key", "locale", "issue_type", "current_value", "candidate_value", "status",
            "review_note", "source_old_value", "source_hash", "suggested_hash", "plan_id", "generated_at",
        ],
        queue_like,
        sheet_name="Review Queue",
    )

    with pytest.raises(AuditRuntimeError):
        run_apply(runtime, queue_like, out_final_json=str(runtime.results_dir / "final.json"))


def test_apply_rejects_duplicate_application(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(plan_id="plan-1"),
            _review_row(key="keep", current_value="كما هو", source_old_value="كما هو", source_hash=compute_text_hash("كما هو"), plan_id="plan-2"),
        ],
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    reasons = [item["reason"] for item in report["skipped"]]
    assert "duplicate_application" in reasons
    assert runtime.metadata["applied_suggestions"] == [compute_text_hash("مرحبا")]


def test_apply_skips_non_approved_final_rows_with_explicit_reason(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    final_workbook = runtime.results_dir / "review" / "review_final.xlsx"
    _write_review_queue(final_workbook, [_review_row(status="pending")])

    report = run_apply(runtime, final_workbook, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["summary"]["approved_rows_skipped"] == 1
    assert report["skipped"][0]["reason"] == "not_approved_status"


def test_apply_accepts_valid_row(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    out_final = runtime.results_dir / "final.json"
    _write_review_queue(review_queue, [_review_row()])

    report = run_apply(runtime, review_queue, out_final_json=str(out_final))

    payload = json.loads(out_final.read_text(encoding="utf-8"))
    assert report["summary"]["approved_rows_applied"] == 1
    assert payload["welcome"] == "مرحبا"
    assert runtime.metadata["applied_suggestions"] == [compute_text_hash("مرحبا")]


def test_apply_rejects_stale_row(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    _write_json(runtime.ar_file, {"welcome": "تم التغيير", "keep": "كما هو"})
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row()])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["summary"]["approved_rows_applied"] == 0
    assert report["skipped"][0]["reason"] == "source_hash_mismatch"


def test_apply_records_all_rejections_in_metadata(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(plan_id="plan-missing", current_value=""),
            _review_row(plan_id="plan-tampered", approved_new="تم تحريرها يدويًا"),
            _review_row(plan_id="plan-stale", source_hash=compute_text_hash("قيمة قديمة")),
        ],
    )

    run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    reasons = [item["reason"] for item in runtime.metadata["apply_rejections"]]
    assert reasons == [
        "missing_required_fields",
        "tampered_row_detected",
        "source_hash_mismatch",
    ]


def test_apply_trace_contains_applied_and_skipped_rows(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(plan_id="plan-applied"),
            _review_row(plan_id="plan-skipped", approved_new="تم تحريرها يدويًا"),
        ],
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert report["trace"] == runtime.metadata["apply_trace"]
    assert [entry["status"] for entry in report["trace"]] == ["applied", "skipped"]
    assert report["trace"][0]["reason"] is None
    assert report["trace"][1]["reason"] == "tampered_row_detected"


def test_apply_trace_order_is_deterministic(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(plan_id="plan-1"),
            _review_row(plan_id="plan-2", approved_new="تم تحريرها يدويًا"),
            _review_row(plan_id="plan-3", source_hash=compute_text_hash("قيمة قديمة")),
        ],
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert [entry["plan_id"] for entry in report["trace"]] == ["plan-1", "plan-2", "plan-3"]
    assert [entry["status"] for entry in report["trace"]] == ["applied", "skipped", "skipped"]


def test_apply_trace_consistency_with_report_views(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(plan_id="plan-applied"),
            _review_row(plan_id="plan-skipped", approved_new="تم تحريرها يدويًا"),
        ],
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    assert len(report["trace"]) == 2
    assert len(report["applied"]) == report["summary"]["approved_rows_applied"] == 1
    assert len(report["skipped"]) == report["summary"]["approved_rows_skipped"] == 1
    applied_trace = [entry for entry in report["trace"] if entry["status"] == "applied"]
    skipped_trace = [entry for entry in report["trace"] if entry["status"] == "skipped"]
    assert len(applied_trace) == len(report["applied"])
    assert len(skipped_trace) == len(report["skipped"])
    assert applied_trace[0]["plan_id"] == report["applied"][0]["plan_id"]
    assert applied_trace[0]["suggested_hash"] == report["applied"][0]["suggested_hash"]
    assert skipped_trace[0]["reason"] == report["skipped"][0]["reason"]


def test_trace_contains_decision_context(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row()])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    entry = report["trace"][0]
    assert "decision_context" in entry
    assert entry["decision_context"]["validation_passed"] is True


def test_trace_context_for_hash_mismatch(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(review_queue, [_review_row(source_hash=compute_text_hash("قيمة قديمة"))])

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    ctx = report["trace"][0]["decision_context"]
    assert ctx["expected_source_hash"] != ctx["actual_current_hash"]
    assert "current_value" in ctx


def test_all_trace_entries_have_context(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    review_queue = runtime.results_dir / "review" / "review_queue.xlsx"
    _write_review_queue(
        review_queue,
        [
            _review_row(),
            _review_row(approved_new="تم تحريرها يدويًا"),
        ],
    )

    report = run_apply(runtime, review_queue, out_final_json=str(runtime.results_dir / "final.json"))

    for entry in report["trace"]:
        assert "decision_context" in entry
        assert isinstance(entry["decision_context"], dict)
