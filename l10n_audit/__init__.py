"""
l10n_audit — Public Python API for the L10n Audit Toolkit.

Usage::

    from l10n_audit import run_audit, init_workspace, doctor_workspace
    from l10n_audit import AuditResult, AuditIssue, AuditOptions

    result = run_audit("/path/to/project", stage="fast")
    print(result.summary.missing_keys)
    print(result.to_dict())
"""

__version__ = "1.7.1"
 
from l10n_audit.api import (
    doctor_workspace,
    init_workspace,
    run_audit,
)
from l10n_audit.exceptions import (
    AIConfigError,
    AuditError,
    InvalidProjectError,
    ReportWriteError,
    UnsupportedFrameworkError,
)
from l10n_audit.models import (
    AuditIssue,
    AuditOptions,
    AuditResult,
    AuditSummary,
    ReportArtifact,
)

__all__ = [
    # API functions
    "run_audit",
    "init_workspace",
    "doctor_workspace",
    # Models
    "AuditResult",
    "AuditIssue",
    "AuditOptions",
    "AuditSummary",
    "ReportArtifact",
    # Exceptions
    "AuditError",
    "InvalidProjectError",
    "UnsupportedFrameworkError",
    "AIConfigError",
    "ReportWriteError",
]
