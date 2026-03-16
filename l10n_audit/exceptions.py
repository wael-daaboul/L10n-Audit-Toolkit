"""
Custom exception hierarchy for the l10n_audit Python API.

All exceptions inherit from :class:`AuditError` so callers can catch
any toolkit error with a single ``except AuditError``.
"""

from __future__ import annotations


class AuditError(RuntimeError):
    """Base exception for all l10n_audit errors."""


class InvalidProjectError(AuditError):
    """Raised when a project path is missing, unreadable, or lacks
    required translation files / workspace configuration."""


class UnsupportedFrameworkError(AuditError):
    """Raised when the detected project profile is not supported by the
    requested audit stage."""


class AIConfigError(AuditError):
    """Raised when AI Review is enabled but the configuration is
    incomplete (e.g. missing API key, bad model name)."""


class ReportWriteError(AuditError):
    """Raised when a report file cannot be written to disk (e.g.
    permission denied, disk full)."""


class StageError(AuditError):
    """Raised when an unknown or invalid audit stage is requested."""
