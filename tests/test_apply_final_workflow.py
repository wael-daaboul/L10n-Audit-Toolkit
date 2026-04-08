import json
from pathlib import Path
from types import SimpleNamespace

from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
from l10n_audit.fixes.apply_review_fixes import run_apply
from l10n_audit.fixes.fix_merger import prepare_apply_workbook


QUEUE_COLUMNS = [
    "key",
    "locale",
    "issue_type",
    "current_value",
    "candidate_value",
    "status",
    "review_note",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
]


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


def test_queue_prepare_apply_apply_end_to_end(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    queue = runtime.results_dir / "review" / "review_queue.xlsx"
    final = runtime.results_dir / "review" / "review_final.xlsx"
    rejection_report = runtime.results_dir / ".cache" / "apply" / "rejection_report.json"
    out_final = runtime.results_dir / "final.json"

    write_simple_xlsx(
        [
            {
                "key": "welcome",
                "locale": "ar",
                "issue_type": "confirmed_missing_key",
                "current_value": "اهلا",
                "candidate_value": "مرحبا",
                "status": "approved",
                "review_note": "ready",
                "source_old_value": "اهلا",
                "source_hash": compute_text_hash("اهلا"),
                "suggested_hash": compute_text_hash("مرحبا"),
                "plan_id": "plan-1",
                "generated_at": "2026-04-08T00:00:00+00:00",
            }
        ],
        QUEUE_COLUMNS,
        queue,
        sheet_name="Review Queue",
    )

    prepare_apply_workbook(queue, final, rejection_report)
    report = run_apply(runtime, final, out_final_json=str(out_final))
    payload = json.loads(out_final.read_text(encoding="utf-8"))

    assert final.exists()
    assert payload["welcome"] == "مرحبا"
    assert report["summary"]["approved_rows_applied"] == 1
    assert report["summary"]["approved_rows_skipped"] == 0
