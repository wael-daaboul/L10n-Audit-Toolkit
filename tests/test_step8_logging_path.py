"""
Step 8 regression tests — consumer/logging path.

Verifies that:
1. setup_audit_logger() does NOT create a relative 'logs/' directory at
   import/call time when no log_dir is provided.
2. setup_audit_logger(log_dir=...) writes to the supplied absolute path.
3. configure_audit_logger_path() attaches a FileHandler at the given path and
   removes any pre-existing NullHandler.
4. The module-level audit_logger uses a NullHandler (no stray CWD writes).

Note: provider.py has a top-level ``import litellm`` which is not available in
the test environment.  All tests import provider with litellm mocked so the
rest of the module is not exercised.
"""
from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Sentinel used by _import_provider_stubbed to distinguish "key absent" from "key → None"
_MISSING = object()


# ---------------------------------------------------------------------------
# Helper: import provider.py with litellm stubbed out
# ---------------------------------------------------------------------------

def _import_provider_stubbed():
    """Return the provider module with litellm replaced by a MagicMock.

    Saves and restores previous sys.modules entries for both 'litellm' and
    'l10n_audit.ai.provider' so that other test modules (e.g. test_v1_3_0_logic)
    whose litellm stub was installed at collection time are not disrupted.
    """
    _prev_litellm = sys.modules.get("litellm", _MISSING)
    _prev_provider = sys.modules.get("l10n_audit.ai.provider", _MISSING)

    # Temporarily replace litellm with a minimal stub so provider.py imports cleanly.
    stub = types.ModuleType("litellm")
    stub.completion = MagicMock()
    sys.modules["litellm"] = stub
    sys.modules.pop("l10n_audit.ai.provider", None)

    try:
        import l10n_audit.ai.provider as provider
        return provider
    finally:
        # Restore previous state: put back whatever was there (or remove if absent).
        if _prev_litellm is _MISSING:
            sys.modules.pop("litellm", None)
        else:
            sys.modules["litellm"] = _prev_litellm

        if _prev_provider is _MISSING:
            sys.modules.pop("l10n_audit.ai.provider", None)
        else:
            sys.modules["l10n_audit.ai.provider"] = _prev_provider


# ---------------------------------------------------------------------------
# Test: no CWD-relative 'logs/' directory is created at import/call time
# ---------------------------------------------------------------------------

def test_setup_audit_logger_no_cwd_directory_created(tmp_path: Path) -> None:
    """setup_audit_logger() with no arguments must NOT create a 'logs/' directory
    in the current working directory."""
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        provider = _import_provider_stubbed()

        _logger = logging.getLogger("l10n_audit.audit_errors_no_cwd_step8")
        for h in list(_logger.handlers):
            _logger.removeHandler(h)
        with patch("logging.getLogger", return_value=_logger):
            provider.setup_audit_logger()

        stray_logs = tmp_path / "logs"
        assert not stray_logs.exists(), (
            f"setup_audit_logger() created a stray 'logs/' directory at {stray_logs}. "
            "The function must not bind to CWD when no log_dir is provided."
        )
    finally:
        os.chdir(original_cwd)


def test_module_level_audit_logger_uses_null_handler(tmp_path: Path) -> None:
    """The module-level audit_logger must not hold a FileHandler with a relative path."""
    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        _import_provider_stubbed()
        _logger = logging.getLogger("l10n_audit.audit_errors")
        file_handlers = [h for h in _logger.handlers if isinstance(h, logging.FileHandler)]
        for fh in file_handlers:
            p = Path(fh.baseFilename)
            assert p.is_absolute(), (
                f"audit_logger has a FileHandler with a relative path: {fh.baseFilename!r}. "
                "Paths must be absolute to avoid CWD-relative log files."
            )
        stray_logs = tmp_path / "logs"
        assert not stray_logs.exists(), (
            f"Importing provider created stray 'logs/' in CWD: {stray_logs}"
        )
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# Test: setup_audit_logger(log_dir=...) writes to the supplied absolute path
# ---------------------------------------------------------------------------

def test_setup_audit_logger_with_explicit_log_dir(tmp_path: Path) -> None:
    """When log_dir is provided, setup_audit_logger must create the directory
    and attach a FileHandler pointing there."""
    provider = _import_provider_stubbed()
    log_dir = tmp_path / "my_project" / "Results" / "logs"

    _logger = logging.getLogger("l10n_audit.audit_errors_explicit_step8")
    for h in list(_logger.handlers):
        _logger.removeHandler(h)

    with patch("logging.getLogger", return_value=_logger):
        provider.setup_audit_logger(log_dir=str(log_dir))

    assert log_dir.exists(), f"setup_audit_logger did not create log_dir at {log_dir}"
    file_handlers = [h for h in _logger.handlers if isinstance(h, logging.FileHandler)]
    assert file_handlers, "No FileHandler was added to the logger"
    log_path = Path(file_handlers[0].baseFilename)
    assert log_path.parent == log_dir, (
        f"FileHandler path {log_path} does not live inside {log_dir}"
    )
    assert log_path.name == "audit_errors.log"


# ---------------------------------------------------------------------------
# Test: configure_audit_logger_path replaces NullHandler with FileHandler
# ---------------------------------------------------------------------------

def test_configure_audit_logger_path_replaces_null_handler(tmp_path: Path) -> None:
    """configure_audit_logger_path must remove any NullHandler and add a
    FileHandler pointing to <log_dir>/audit_errors.log."""
    provider = _import_provider_stubbed()

    _logger = logging.getLogger("l10n_audit.audit_errors_configure_step8")
    for h in list(_logger.handlers):
        _logger.removeHandler(h)
    _logger.addHandler(logging.NullHandler())
    _logger.setLevel(logging.ERROR)

    log_dir = tmp_path / "Results" / "logs"

    with patch("logging.getLogger", return_value=_logger):
        provider.configure_audit_logger_path(log_dir)

    null_handlers = [h for h in _logger.handlers if isinstance(h, logging.NullHandler)]
    file_handlers = [h for h in _logger.handlers if isinstance(h, logging.FileHandler)]

    assert not null_handlers, "NullHandler was not removed after configure_audit_logger_path"
    assert file_handlers, "No FileHandler was added by configure_audit_logger_path"
    assert Path(file_handlers[0].baseFilename).parent == log_dir


def test_configure_audit_logger_path_idempotent(tmp_path: Path) -> None:
    """Calling configure_audit_logger_path twice with the same path must not
    create duplicate FileHandlers."""
    provider = _import_provider_stubbed()

    _logger = logging.getLogger("l10n_audit.audit_errors_idempotent_step8")
    for h in list(_logger.handlers):
        _logger.removeHandler(h)
    log_dir = tmp_path / "Results" / "logs"

    with patch("logging.getLogger", return_value=_logger):
        provider.configure_audit_logger_path(log_dir)
        provider.configure_audit_logger_path(log_dir)

    file_handlers = [h for h in _logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1, (
        f"Expected 1 FileHandler after idempotent calls, got {len(file_handlers)}"
    )
