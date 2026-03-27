import os
import pytest
from unittest.mock import patch
from l10n_audit.core.utils import check_java_available

def test_check_java_skip_env():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "true"}):
        assert check_java_available() is True

def test_check_java_mock_missing():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "false"}):
        with patch("shutil.which", return_value=None):
            assert check_java_available() is False

def test_check_java_mock_found():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "false"}):
        with patch("shutil.which", return_value="/usr/bin/java"):
            assert check_java_available() is True
