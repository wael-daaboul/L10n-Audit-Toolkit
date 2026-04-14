import json
from pathlib import Path

from l10n_audit.core.audit_runtime import compute_text_hash, read_simple_xlsx, write_simple_xlsx
from l10n_audit.fixes.fix_merger import REVIEW_FINAL_COLUMNS, prepare_apply_workbook


QUEUE_COLUMNS = [
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


def _queue_row(**overrides):
    row = {
        "key": "welcome",
        "locale": "ar",
        "issue_type": "grammar",
        "current_value": "اهلا",
        "candidate_value": "مرحبا",
        "status": "approved",
        "review_note": "ok",
        "source_old_value": "اهلا",
        "source_hash": compute_text_hash("اهلا"),
        "suggested_hash": compute_text_hash("مرحبا"),
        "plan_id": "plan-1",
        "generated_at": "2026-04-08T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _write_queue(path: Path, rows: list[dict]) -> None:
    write_simple_xlsx(rows, QUEUE_COLUMNS, path, sheet_name="Review Queue")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_prepare_apply_happy_path(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row()])

    payload = prepare_apply_workbook(queue, final, report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

    assert payload["summary"] == {"total_rows": 1, "accepted_rows": 1, "rejected_rows": 0}
    assert len(rows) == 1
    assert rows[0]["approved_new"] == "مرحبا"
    assert rows[0]["source_hash"] == compute_text_hash("اهلا")
    assert rows[0]["suggested_hash"] == compute_text_hash("مرحبا")


def test_prepare_apply_rejects_divergent_human_edits(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    # Provide candidate_value and approved_new that differ
    _write_queue(queue, [_queue_row(candidate_value="أهلًا بك", approved_new="مرحبا", suggested_hash=compute_text_hash("مرحبا"))])

    prepare_apply_workbook(queue, final, report)
    payload = _read_json(report)

    assert payload["summary"]["accepted_rows"] == 0
    assert payload["rejections"][0]["reason_code"] == "divergent_human_edits"
    assert payload["rejections"][0]["details"]["candidate_value"] == "أهلًا بك"
    assert payload["rejections"][0]["details"]["approved_new"] == "مرحبا"


def test_prepare_apply_accepts_fallback_combinations(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    
    _write_queue(queue, [
        # 1: Only candidate_value
        _queue_row(key="k1", candidate_value="hello", approved_new=""),
        # 2: Only approved_new
        _queue_row(key="k2", candidate_value="", approved_new="hello"),
        # 3: Both populated and matching
        _queue_row(key="k3", candidate_value="hello", approved_new="hello"),
    ])

    prepare_apply_workbook(queue, final, report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
    
    assert len(rows) == 3
    assert rows[0]["approved_new"] == "hello"
    assert rows[1]["approved_new"] == "hello"
    assert rows[2]["approved_new"] == "hello"


def test_prepare_apply_rejects_pending_rows(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(status="pending")])

    prepare_apply_workbook(queue, final, report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
    payload = _read_json(report)

    assert rows == []
    assert payload["summary"]["accepted_rows"] == 0
    assert payload["rejections"][0]["reason_code"] == "invalid_status_for_freeze"


def test_prepare_apply_rejects_missing_final_text(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(candidate_value="", approved_new="", suggested_hash=compute_text_hash(""))])

    prepare_apply_workbook(queue, final, report)
    payload = _read_json(report)

    assert payload["rejections"][0]["reason_code"] == "missing_final_text"


def test_prepare_apply_rejects_source_old_value_current_value_mismatch(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(source_old_value="قيمة مختلفة")])

    prepare_apply_workbook(queue, final, report)
    payload = _read_json(report)

    assert payload["rejections"][0]["reason_code"] == "source_value_mismatch"


def test_prepare_apply_rejects_source_hash_mismatch(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(source_hash=compute_text_hash("قيمة مختلفة"))])

    prepare_apply_workbook(queue, final, report)
    payload = _read_json(report)

    assert payload["rejections"][0]["reason_code"] == "source_hash_mismatch"


def test_prepare_apply_rejects_unresolved_lookup_source_hash_sentinel(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(source_hash="__UNRESOLVED_LOOKUP__")])

    prepare_apply_workbook(queue, final, report)
    payload = _read_json(report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

    assert rows == []
    assert payload["rejections"][0]["reason_code"] == "source_hash_mismatch"
    assert payload["rejections"][0]["details"]["actual_source_hash"] == "__UNRESOLVED_LOOKUP__"


def test_prepare_apply_is_idempotent(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(queue, [_queue_row(), _queue_row(plan_id="plan-2", status="pending")])

    prepare_apply_workbook(queue, final, report)
    first_rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
    first_report = _read_json(report)

    prepare_apply_workbook(queue, final, report)
    second_rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)
    second_report = _read_json(report)

    assert first_rows == second_rows
    assert first_report == second_report


def test_prepare_apply_mixed_rows_accepts_only_valid_rows(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    _write_queue(
        queue,
        [
            _queue_row(plan_id="plan-ok"),
            _queue_row(plan_id="plan-pending", status="pending"),
            _queue_row(plan_id="plan-hash", source_hash=compute_text_hash("قيمة مختلفة")),
        ],
    )

    payload = prepare_apply_workbook(queue, final, report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

    assert payload["summary"] == {"total_rows": 3, "accepted_rows": 1, "rejected_rows": 2}
    assert len(rows) == 1
    assert rows[0]["plan_id"] == "plan-ok"
    assert {item["reason_code"] for item in payload["rejections"]} == {
        "invalid_status_for_freeze",
        "source_hash_mismatch",
    }


def test_prepare_apply_accepts_human_edited_candidate_value(tmp_path: Path) -> None:
    queue = tmp_path / "review_queue.xlsx"
    final = tmp_path / "review_final.xlsx"
    report = tmp_path / "rejection_report.json"
    
    # Original machine suggestion was "مرحبا", human edited it to "مرحبا بك"
    # suggested_hash still points to "مرحبا", simulating a realistic edit where hashes drift.
    _write_queue(queue, [_queue_row(candidate_value="مرحبا بك", suggested_hash=compute_text_hash("مرحبا"))])

    payload = prepare_apply_workbook(queue, final, report)
    rows = read_simple_xlsx(final, required_columns=REVIEW_FINAL_COLUMNS)

    assert payload["summary"]["accepted_rows"] == 1
    assert payload["summary"]["rejected_rows"] == 0
    assert len(rows) == 1
    
    # ensure candidate_value mutation was gracefully accepted and passed through
    assert rows[0]["candidate_value"] == "مرحبا بك"
    assert rows[0]["approved_new"] == "مرحبا بك"
    assert rows[0]["suggested_hash"] == compute_text_hash("مرحبا")




