import pytest
import argparse
import json
from unittest.mock import patch, MagicMock
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
    args = argparse.Namespace(path=".", review_queue=None, out_final=None, rejection_report=None)
    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load, \
         patch("l10n_audit.fixes.fix_merger.prepare_apply_workbook") as mock_prepare, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", side_effect=OSError("no file")):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 3, "accepted_rows": 1, "rejected_rows": 2}
        }

        assert cmd_prepare_apply(args) == 0
        # H3: allowed_plan_ids=None because machine queue could not be read
        mock_prepare.assert_called_once_with(
            Path("results/review/review_queue.xlsx"),
            Path("results/review/review_final.xlsx"),
            Path("results/.cache/apply/rejection_report.json"),
            allowed_plan_ids=None,
        )


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
