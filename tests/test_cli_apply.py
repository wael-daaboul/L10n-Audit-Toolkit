import pytest
import argparse
from unittest.mock import patch, MagicMock
from pathlib import Path
from l10n_audit.core.cli import cmd_apply

def test_cmd_apply_no_queue():
    args = argparse.Namespace(path=".", review_queue="non_existent.xlsx", all=False)
    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.audit_runtime.load_runtime") as mock_load:
        
        mock_runtime = MagicMock()
        mock_runtime.results_dir = Path("results")
        mock_load.return_value = mock_runtime
        
        # Should return 1 if queue doesn't exist
        assert cmd_apply(args) == 1

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
