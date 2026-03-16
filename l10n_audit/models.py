"""
Typed data models for the l10n_audit Python API.

These models define the stable JSON contract returned by :func:`run_audit`.
All models are dataclasses and serialise to / from plain ``dict`` / JSON
so that a downstream web API can pass results directly to a frontend.

Issue Codes
-----------
Each :class:`AuditIssue` carries a machine-readable ``code`` field:

+-------------------------------+--------------------------------------------+
| Code                          | Meaning                                    |
+===============================+============================================+
| MISSING_KEY                   | Key used in code but absent in locale file |
| UNUSED_KEY                    | Key in locale file not found in code       |
| EMPTY_TRANSLATION             | Translation value is empty / whitespace    |
| PLACEHOLDER_MISMATCH          | Placeholder count/names differ             |
| TERMINOLOGY_VIOLATION         | Forbidden term used in translation         |
| ICU_SYNTAX_ERROR              | Invalid ICU message format                 |
| GRAMMAR_ERROR                 | Grammar / spelling issue                   |
| AR_QC                         | Arabic locale quality-control issue        |
| AR_SEMANTIC                   | Arabic semantic / meaning issue            |
| AI_SUGGESTION                 | AI-generated suggested improvement         |
| NEEDS_MANUAL_REVIEW           | Ambiguous item needing human review        |
| DYNAMIC_INFERRED_USAGE        | Key likely used via dynamic expression     |
| MISSING_KEY_AR                | Key present in EN but absent in AR         |
| MISSING_KEY_EN                | Key present in AR but absent in EN         |
| UNKNOWN                       | Unclassified issue                         |
+-------------------------------+--------------------------------------------+
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

VALID_STAGES = frozenset(
    {
        "fast",
        "full",
        "grammar",
        "terminology",
        "placeholders",
        "ar-qc",
        "ar-semantic",
        "icu",
        "reports",
        "autofix",
        "ai-review",
    }
)

IssueCode = Literal[
    "MISSING_KEY",
    "MISSING_KEY_AR",
    "MISSING_KEY_EN",
    "UNUSED_KEY",
    "EMPTY_TRANSLATION",
    "PLACEHOLDER_MISMATCH",
    "TERMINOLOGY_VIOLATION",
    "ICU_SYNTAX_ERROR",
    "GRAMMAR_ERROR",
    "AR_QC",
    "AR_SEMANTIC",
    "AI_SUGGESTION",
    "NEEDS_MANUAL_REVIEW",
    "DYNAMIC_INFERRED_USAGE",
    "UNKNOWN",
]

Severity = Literal["error", "warning", "info"]


@dataclass
class AuditIssue:
    """A single localisation issue found during an audit run.

    Parameters
    ----------
    key:
        The translation key this issue relates to.
    code:
        Machine-readable issue code (see module docstring table).
    issue_type:
        Legacy string from the existing audit modules — kept for backward
        compatibility with existing JSON consumers.
    severity:
        ``"error"`` | ``"warning"`` | ``"info"``
    locale:
        Locale identifier (e.g. ``"ar"``, ``"en"``, ``"en/ar"``).
    message:
        Human-readable description.
    file:
        Source file path where the issue was detected (if applicable).
    line:
        Line number in *file* (if applicable).
    suggestion:
        Suggested correction (populated by AI review stage).
    source:
        Original source-language string (populated by AI review stage).
    target:
        Current translation string (populated by AI review stage).
    extra:
        Arbitrary additional data from the underlying audit module.
    """

    key: str = ""
    code: IssueCode = "UNKNOWN"
    issue_type: str = ""
    severity: Severity = "warning"
    locale: str = ""
    message: str = ""
    file: str = ""
    line: int | None = None
    suggestion: str = ""
    source: str = ""
    target: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Remove None values for cleaner JSON
        return {k: v for k, v in d.items() if v is not None}


# ---------------------------------------------------------------------------
# Mapping from legacy issue_type strings → IssueCode
# ---------------------------------------------------------------------------

_ISSUE_TYPE_TO_CODE: dict[str, IssueCode] = {
    "missing_in_both": "MISSING_KEY",
    "missing_ar": "MISSING_KEY_AR",
    "missing_in_ar": "MISSING_KEY_AR",
    "in_en_not_ar": "MISSING_KEY_AR",
    "missing_en": "MISSING_KEY_EN",
    "missing_in_en": "MISSING_KEY_EN",
    "in_ar_not_en": "MISSING_KEY_EN",
    "unused_ar": "UNUSED_KEY",
    "unused_en": "UNUSED_KEY",
    "confirmed_unused_key": "UNUSED_KEY",
    "empty_ar": "EMPTY_TRANSLATION",
    "empty_en": "EMPTY_TRANSLATION",
    "placeholder_mismatch": "PLACEHOLDER_MISMATCH",
    "placeholder": "PLACEHOLDER_MISMATCH",
    "terminology": "TERMINOLOGY_VIOLATION",
    "terminology_violation": "TERMINOLOGY_VIOLATION",
    "icu_error": "ICU_SYNTAX_ERROR",
    "icu_syntax_error": "ICU_SYNTAX_ERROR",
    "grammar_error": "GRAMMAR_ERROR",
    "grammar": "GRAMMAR_ERROR",
    "ar_qc": "AR_QC",
    "ar_locale_qc": "AR_QC",
    "ar_semantic": "AR_SEMANTIC",
    "ar_semantic_qc": "AR_SEMANTIC",
    "ai_suggestion": "AI_SUGGESTION",
    "needs_manual_review": "NEEDS_MANUAL_REVIEW",
    "suspicious_usage": "NEEDS_MANUAL_REVIEW",
    "dynamic_inferred_usage": "DYNAMIC_INFERRED_USAGE",
    "dynamic_inferred_ar": "DYNAMIC_INFERRED_USAGE",
    "dynamic_inferred_en": "DYNAMIC_INFERRED_USAGE",
}


def issue_code_from_type(issue_type: str) -> IssueCode:
    """Convert a legacy *issue_type* string to an :data:`IssueCode`."""
    return _ISSUE_TYPE_TO_CODE.get(issue_type.lower(), "UNKNOWN")


def issue_from_dict(raw: dict[str, Any]) -> AuditIssue:
    """Create an :class:`AuditIssue` from a raw dict (from any audit module)."""
    issue_type = str(raw.get("issue_type") or raw.get("type") or "")
    code: IssueCode = raw.get("code") or issue_code_from_type(issue_type)  # type: ignore[assignment]
    file_val = raw.get("file") or ""
    if isinstance(file_val, Path):
        file_val = str(file_val)
    return AuditIssue(
        key=str(raw.get("key") or ""),
        code=code,
        issue_type=issue_type,
        severity=raw.get("severity", "warning"),
        locale=str(raw.get("locale") or ""),
        message=str(raw.get("message") or raw.get("description") or ""),
        file=str(file_val),
        line=raw.get("line"),
        suggestion=str(raw.get("suggestion") or ""),
        source=str(raw.get("source") or ""),
        target=str(raw.get("target") or raw.get("current_translation") or ""),
        extra={k: v for k, v in raw.items() if k not in {
            "key", "code", "issue_type", "type", "severity", "locale",
            "message", "description", "file", "line", "suggestion",
            "source", "target", "current_translation",
        }},
    )


# ---------------------------------------------------------------------------
# AuditSummary
# ---------------------------------------------------------------------------

@dataclass
class AuditSummary:
    """Aggregate counts from all audit stages in a single run."""

    total_keys_en: int = 0
    total_keys_ar: int = 0
    missing_keys: int = 0
    unused_keys: int = 0
    empty_translations: int = 0
    placeholder_errors: int = 0
    terminology_errors: int = 0
    icu_errors: int = 0
    grammar_errors: int = 0
    ar_qc_issues: int = 0
    ar_semantic_issues: int = 0
    ai_suggestions: int = 0
    needs_manual_review: int = 0
    total_issues: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_issues(cls, issues: list[AuditIssue]) -> "AuditSummary":
        """Build a summary by counting issues list."""
        s = cls()
        s.total_issues = len(issues)
        for issue in issues:
            code = issue.code
            if code in ("MISSING_KEY", "MISSING_KEY_AR", "MISSING_KEY_EN"):
                s.missing_keys += 1
            elif code == "UNUSED_KEY":
                s.unused_keys += 1
            elif code == "EMPTY_TRANSLATION":
                s.empty_translations += 1
            elif code == "PLACEHOLDER_MISMATCH":
                s.placeholder_errors += 1
            elif code == "TERMINOLOGY_VIOLATION":
                s.terminology_errors += 1
            elif code == "ICU_SYNTAX_ERROR":
                s.icu_errors += 1
            elif code == "GRAMMAR_ERROR":
                s.grammar_errors += 1
            elif code == "AR_QC":
                s.ar_qc_issues += 1
            elif code == "AR_SEMANTIC":
                s.ar_semantic_issues += 1
            elif code == "AI_SUGGESTION":
                s.ai_suggestions += 1
            elif code == "NEEDS_MANUAL_REVIEW":
                s.needs_manual_review += 1
        return s


# ---------------------------------------------------------------------------
# ReportArtifact
# ---------------------------------------------------------------------------

@dataclass
class ReportArtifact:
    """Metadata about a report file written to disk."""

    name: str
    """Human-readable report name, e.g. ``"localization_audit_pro_en"``."""

    path: str
    """Absolute path to the written file."""

    format: Literal["json", "md", "xlsx", "csv", "markdown"]
    """File format."""

    category: Literal["summary", "tool", "review", "logs"] = "tool"
    """Report category."""

    size_bytes: int = 0
    """File size in bytes after writing."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# AuditOptions
# ---------------------------------------------------------------------------

@dataclass
class AuditOptions:
    """Options controlling a single :func:`run_audit` invocation."""

    stage: str = "full"
    ai_enabled: bool = False
    ai_api_key: str | None = None
    ai_model: str | None = None
    ai_api_base: str | None = None
    write_reports: bool = True
    output_dir: str | Path | None = None

    def effective_output_dir(self, default: Path) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return default

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("output_dir") is not None:
            d["output_dir"] = str(d["output_dir"])
        # Never serialise API key
        d.pop("ai_api_key", None)
        return d


# ---------------------------------------------------------------------------
# AuditResult
# ---------------------------------------------------------------------------

@dataclass
class AuditResult:
    """The top-level result of a :func:`run_audit` call.

    All fields serialise deterministically via :meth:`to_dict` / :meth:`to_json`
    so that downstream HTTP APIs can pass them directly to a frontend.

    Run Metadata
    ------------
    job_id:
        A UUID string uniquely identifying this run.
    started_at:
        ISO-8601 UTC timestamp of when the run started.
    finished_at:
        ISO-8601 UTC timestamp of when the run finished.
    duration_ms:
        Wall-clock duration in milliseconds.
    """

    # Identifiers
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str = ""
    profile: str = ""
    stage: str = ""

    # Run metadata
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0

    # Results
    summary: AuditSummary = field(default_factory=AuditSummary)
    issues: list[AuditIssue] = field(default_factory=list)
    reports: list[ReportArtifact] = field(default_factory=list)

    # Status
    success: bool = True
    error_message: str = ""

    # ------------------------------------------------------------------ #

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def mark_started(self) -> None:
        self.started_at = self._now_iso()
        self._start_ts = datetime.now(timezone.utc).timestamp()

    def mark_finished(self) -> None:
        self.finished_at = self._now_iso()
        if hasattr(self, "_start_ts"):
            self.duration_ms = int(
                (datetime.now(timezone.utc).timestamp() - self._start_ts) * 1000
            )

    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_path": self.project_path,
            "profile": self.profile,
            "stage": self.stage,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error_message": self.error_message,
            "summary": self.summary.to_dict(),
            "issues": [i.to_dict() for i in self.issues],
            "reports": [r.to_dict() for r in self.reports],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
