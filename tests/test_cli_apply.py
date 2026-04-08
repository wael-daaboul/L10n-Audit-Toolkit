import pytest
import argparse
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
         patch("pathlib.Path.exists", return_value=True):

        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        mock_prepare.return_value = {
            "summary": {"total_rows": 3, "accepted_rows": 1, "rejected_rows": 2}
        }

        assert cmd_prepare_apply(args) == 0
        mock_prepare.assert_called_once_with(
            Path("results/review/review_queue.xlsx"),
            Path("results/review/review_final.xlsx"),
            Path("results/.cache/apply/rejection_report.json"),
        )
