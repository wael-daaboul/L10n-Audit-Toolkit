import pytest
import argparse
import json
from unittest.mock import patch, MagicMock, call
from pathlib import Path
from l10n_audit.core.cli import build_parser, cmd_apply, cmd_prepare_apply

def test_cmd_apply_no_queue(capsys):
    args = argparse.Namespace(path=".", review_queue="non_existent.xlsx", all=False)
    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load:
        
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        
        # Should return 1 if queue doesn't exist
        assert cmd_apply(args) == 1
    output = capsys.readouterr().out
    assert "ERROR: review_final.xlsx not found." in output
    assert "l10n-audit prepare-apply" in output

def test_cmd_apply_success():
    args = argparse.Namespace(path=".", review_queue=None, all=True)
    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.apply_review_fixes.run_apply") as mock_run_apply, \
         patch("pathlib.Path.exists", return_value=True):
        
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        
        mock_run_apply.return_value = {
            "summary": {
                "approved_rows_applied": 5,
                "approved_rows_skipped": 0,
                "en_fixed_files": 1,
                "ar_fixed_files": 1
            }
        }
        
        assert cmd_apply(args) == 0
        mock_run_apply.assert_called_once()
        # Check if apply_all=True was passed
        args_list, kwargs = mock_run_apply.call_args
        assert kwargs["apply_all"] is True
        assert args_list[1] == Path("results/review/review_final.xlsx")


def test_cmd_apply_defaults_to_review_final_workbook():
    parser = build_parser()
    args = parser.parse_args(["apply"])

    assert args.command == "apply"
    assert args.func is cmd_apply
    assert args.review_queue is None
    apply_parser = parser._subparsers._group_actions[0].choices["apply"]
    assert "This command does NOT read review_queue.xlsx directly." in apply_parser.description
    assert "run -> review_queue.xlsx -> prepare-apply -> review_final.xlsx -> apply" in apply_parser.description


def test_cmd_apply_no_silent_fallback_to_review_queue():
    args = argparse.Namespace(path=".", review_queue=None, all=False)

    def fake_exists(path_obj: Path) -> bool:
        return path_obj == Path("results/review/review_queue.xlsx")

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("pathlib.Path.exists", new=fake_exists):
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime

        assert cmd_apply(args) == 1


def test_prepare_apply_subcommand_wiring():
    parser = build_parser()
    args = parser.parse_args(["prepare-apply"])

    assert args.command == "prepare-apply"
    assert args.func is cmd_prepare_apply
    assert args.path == "."
    assert args.review_queue is None
    assert args.out_final is None
    assert args.rejection_report is None


def test_cmd_prepare_apply_success():
    """prepare_apply_workbook is called with both allowed_plan_ids and machine_queue_path."""
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)

    machine_queue_data = {
        "review_queue": [{"plan_id": "plan-1", "key": "k", "locale": "ar"}],
        "plan_id_source": "report_aggregator",
    }

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text",
               return_value=json.dumps(machine_queue_data)):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 3, "accepted_rows": 1, "rejected_rows": 2}
        }

        assert cmd_prepare_apply(args) == 0
        _, kwargs = mock_prepare.call_args
        # H3: allowed_plan_ids derived from machine queue
        assert kwargs["allowed_plan_ids"] == frozenset({"plan-1"})
        # H4: machine_queue_path is forwarded (not None)
        assert kwargs["machine_queue_path"] is not None


# ---------------------------------------------------------------------------
# H4 CLI Wiring Tests
# ---------------------------------------------------------------------------

def test_cli_passes_machine_queue_path_when_available():
    """
    When review_machine_queue.json exists, machine_queue_path must be forwarded
    as a non-None Path to prepare_apply_workbook.
    """
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)

    machine_queue_data = {
        "review_queue": [{"plan_id": "plan-h4", "key": "k", "locale": "ar"}],
        "plan_id_source": "report_aggregator",
    }

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text",
               return_value=json.dumps(machine_queue_data)):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 1, "accepted_rows": 1, "rejected_rows": 0}
        }

        cmd_prepare_apply(args)

        _, kwargs = mock_prepare.call_args
        assert "machine_queue_path" in kwargs, (
            "machine_queue_path must be forwarded to prepare_apply_workbook"
        )
        assert kwargs["machine_queue_path"] is not None, (
            "machine_queue_path must not be None when the machine queue file exists"
        )


def test_cli_falls_back_to_none_when_machine_queue_missing():
    """
    When review_machine_queue.json does NOT exist, machine_queue_path must be
    passed as None so H4 is disabled (not a hard failure).
    """
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)

    def fake_exists(self) -> bool:
        # review_queue.xlsx exists, machine_queue.json does not
        return "review_queue.xlsx" in str(self)

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch.object(Path, "exists", fake_exists):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 0, "accepted_rows": 0, "rejected_rows": 0}
        }

        result = cmd_prepare_apply(args)
        assert result == 0

        _, kwargs = mock_prepare.call_args
        assert kwargs["machine_queue_path"] is None, (
            "machine_queue_path must be None when the machine queue file is absent"
        )


def test_cli_triggers_integrity_drift_rejection(tmp_path):
    """
    End-to-end: CLI path correctly forwards machine_queue_path so that drift
    in an immutable field causes a rejection with reason_code=integrity_drift.
    """
    from l10n_audit.core.audit_runtime import compute_text_hash, write_simple_xlsx
    from l10n_audit.fixes.fix_merger import (
        INTEGRITY_DRIFT_REASON_CODE,
        REVIEW_FINAL_COLUMNS,
    )

    # Build a valid-looking review queue workbook
    queue_columns = [
        "key", "locale", "issue_type", "current_value", "candidate_value",
        "status", "review_note", "source_old_value", "source_hash",
        "suggested_hash", "plan_id", "generated_at",
    ]
    original_value = "فشل تسجيل الدخول"
    original_hash = compute_text_hash(original_value)
    workbook_row = {
        "key": "auth.failed",
        "locale": "ar",
        "issue_type": "locale_qc",
        "current_value": original_value,
        "candidate_value": "فشل.",
        "status": "approved",
        "review_note": "",
        "source_old_value": original_value,
        "source_hash": original_hash,          # correct in workbook
        "suggested_hash": compute_text_hash("فشل."),
        "plan_id": "plan-drift-test",
        "generated_at": "2026-04-13T00:00:00+00:00",
    }
    review_queue = tmp_path / "review_queue.xlsx"
    write_simple_xlsx([workbook_row], queue_columns, review_queue, sheet_name="Review Queue")

    # Machine queue records a DIFFERENT source_hash (simulating tampering detection)
    machine_queue = tmp_path / "review_machine_queue.json"
    machine_queue.write_text(
        json.dumps({
            "review_queue": [{
                **workbook_row,
                "source_hash": "MACHINE_ORIGINAL_HASH",  # differs from workbook
            }],
            "plan_id_source": "report_aggregator",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    out_final = tmp_path / "review_final.xlsx"
    rejection_report = tmp_path / "rejection_report.json"

    args = argparse.Namespace(
        path=".",
        review_queue=str(review_queue),
        out_final=str(out_final),
        rejection_report=str(rejection_report),
    )

    def fake_resolve_machine(runtime):
        return machine_queue

    with patch("l10n_audit.core.cli.find_project_root", return_value=tmp_path), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch(
             "l10n_audit.core.cli.resolve_review_machine_queue_json_path",
             side_effect=fake_resolve_machine,
         ):
        mock_runtime = MagicMock()
        mock_runtime.results_dir = tmp_path
        mock_load.return_value = mock_runtime

        result = cmd_prepare_apply(args)

    assert result == 0  # CLI itself succeeds; drift is a row-level rejection
    report = json.loads(rejection_report.read_text(encoding="utf-8"))
    assert report["summary"]["accepted_rows"] == 0
    assert report["rejections"][0]["reason_code"] == INTEGRITY_DRIFT_REASON_CODE


def test_cmd_prepare_apply_passes_allowed_plan_ids_from_machine_queue():
    """H3: when review_machine_queue.json exists, allowed_plan_ids is derived and passed."""
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)

    machine_queue_content = json.dumps({
        "review_queue": [
            {"plan_id": "plan-abc", "key": "k1"},
            {"plan_id": "plan-xyz", "key": "k2"},
        ],
        "plan_id_source": "report_aggregator",
    })

    def fake_exists(self):
        # review_queue.xlsx and machine queue both "exist"
        return True

    def fake_read_text(self, encoding="utf-8"):
        # Only the machine queue path returns content; others raise
        if "review_machine_queue" in str(self):
            return machine_queue_content
        raise OSError("not the machine queue")

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch("pathlib.Path.exists", fake_exists), \
         patch("pathlib.Path.read_text", fake_read_text):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 2, "accepted_rows": 2, "rejected_rows": 0}
        }

        assert cmd_prepare_apply(args) == 0

        _, kwargs = mock_prepare.call_args
        assert kwargs.get("allowed_plan_ids") == frozenset({"plan-abc", "plan-xyz"})


def test_cmd_prepare_apply_falls_back_to_no_constraint_when_machine_queue_absent():
    """H3: when review_machine_queue.json is absent, allowed_plan_ids=None (backward compat)."""
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)

    def fake_exists(self):
        # review_queue.xlsx exists, but machine queue does not
        return "review_queue.xlsx" in str(self) and "review_machine_queue" not in str(self)

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch("pathlib.Path.exists", fake_exists):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 1, "accepted_rows": 1, "rejected_rows": 0}
        }

        assert cmd_prepare_apply(args) == 0

        _, kwargs = mock_prepare.call_args
        assert kwargs.get("allowed_plan_ids") is None
