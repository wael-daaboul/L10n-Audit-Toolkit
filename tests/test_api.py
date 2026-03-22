import pytest
from pathlib import Path
from l10n_audit.api import run_audit
from l10n_audit.exceptions import InvalidProjectError

def test_run_audit_invalid_path():
    with pytest.raises(InvalidProjectError) as exc:
        run_audit("/non/existent/path/for/api/test")
    assert "does not exist" in str(exc.value)

def test_run_audit_empty_dir_project(tmp_path):
    # This should fail validation because it has no .l10n-audit or signals
    with pytest.raises(InvalidProjectError) as exc:
        run_audit(tmp_path)
    assert "Invalid project configuration" in str(exc.value)
