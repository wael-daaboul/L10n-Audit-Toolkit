"""
Core engine — dispatches audit stages to Python functions directly.

No ``subprocess`` is used.  Each audit stage calls the corresponding
audit module's :func:`run_stage` function in-process.

The engine is the heart of :func:`l10n_audit.api.run_audit`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from l10n_audit.exceptions import AuditError, ReportWriteError, StageError
from l10n_audit.models import (
    AuditIssue,
    AuditOptions,
    AuditResult,
    AuditSummary,
    ReportArtifact,
    VALID_STAGES,
    issue_from_dict,
)

if TYPE_CHECKING:
    from l10n_audit.core.ai_protocol import AIProvider

logger = logging.getLogger("l10n_audit.engine")


# ---------------------------------------------------------------------------
# Stage → module function mapping
# ---------------------------------------------------------------------------

def _run_l10n_audit_pro(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.l10n_audit_pro import run_stage
    return run_stage(runtime, options)


def _run_en_locale_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.en_locale_qc import run_stage
    return run_stage(runtime, options)


def _run_ar_locale_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.ar_locale_qc import run_stage
    return run_stage(runtime, options)


def _run_ar_semantic_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.ar_semantic_qc import run_stage
    return run_stage(runtime, options)


def _run_placeholder_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.placeholder_audit import run_stage
    return run_stage(runtime, options)


def _run_terminology_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.terminology_audit import run_stage
    return run_stage(runtime, options)


def _run_icu_message_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.icu_message_audit import run_stage
    return run_stage(runtime, options)


def _run_en_grammar_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from audits.en_grammar_audit import run_stage
    return run_stage(runtime, options)


def _run_ai_review(runtime, options: AuditOptions, ai_provider=None) -> list[AuditIssue]:
    from audits.ai_review import run_stage
    return run_stage(runtime, options, ai_provider=ai_provider)


def _run_report_aggregator(runtime, options: AuditOptions, **_) -> list[ReportArtifact]:
    from reports.report_aggregator import run_stage
    return run_stage(runtime, options)


def _run_autofix(runtime, options: AuditOptions) -> list[AuditIssue]:
    from fixes.apply_safe_fixes import run_stage
    return run_stage(runtime, options)


# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

_FAST_SOURCES = "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders"
_FULL_SOURCES = "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders,icu_message_audit,grammar"


def _dispatch_stage(
    stage: str,
    runtime,
    options: AuditOptions,
    ai_provider,
) -> tuple[list[AuditIssue], list[ReportArtifact]]:
    """Run all sub-steps for *stage*.

    Returns
    -------
    issues : list[AuditIssue]
    reports : list[ReportArtifact]
    """
    issues: list[AuditIssue] = []
    reports: list[ReportArtifact] = []

    def _collect(*fns):
        for fn in fns:
            try:
                result = fn()
                if result:
                    issues.extend(result)
            except Exception as exc:
                logger.warning("Stage sub-step failed: %s", exc)
                issues.append(
                    AuditIssue(
                        key="ENGINE_FAILURE",
                        code="ENGINE_ERROR",
                        issue_type="engine_error",
                        severity="error",
                        message=f"Audit stage sub-step failed: {exc}",
                    )
                )

    def _collect_reports(*fns):
        for fn in fns:
            try:
                result = fn()
                if result:
                    reports.extend(result)
            except Exception as exc:
                logger.warning("Report step failed: %s", exc)

    if stage == "fast":
        _collect(
            lambda: _run_l10n_audit_pro(runtime, options),
            lambda: _run_en_locale_qc(runtime, options),
            lambda: _run_ar_locale_qc(runtime, options),
            lambda: _run_ar_semantic_qc(runtime, options),
            lambda: _run_placeholder_audit(runtime, options),
            lambda: _run_terminology_audit(runtime, options),
        )
        if options.write_reports:
            _collect_reports(lambda: _run_report_aggregator(runtime, options, sources=_FAST_SOURCES))

    elif stage == "full":
        _collect(
            lambda: _run_l10n_audit_pro(runtime, options),
            lambda: _run_en_locale_qc(runtime, options),
            lambda: _run_ar_locale_qc(runtime, options),
            lambda: _run_ar_semantic_qc(runtime, options),
            lambda: _run_placeholder_audit(runtime, options),
            lambda: _run_terminology_audit(runtime, options),
            lambda: _run_icu_message_audit(runtime, options),
            lambda: _run_en_grammar_audit(runtime, options),
        )
        if options.write_reports:
            _collect_reports(lambda: _run_report_aggregator(runtime, options, sources=_FULL_SOURCES))

    elif stage == "grammar":
        _collect(lambda: _run_en_grammar_audit(runtime, options))

    elif stage == "terminology":
        _collect(lambda: _run_terminology_audit(runtime, options))

    elif stage == "placeholders":
        _collect(lambda: _run_placeholder_audit(runtime, options))

    elif stage == "ar-qc":
        _collect(lambda: _run_ar_locale_qc(runtime, options))

    elif stage == "ar-semantic":
        _collect(lambda: _run_ar_semantic_qc(runtime, options))

    elif stage == "icu":
        _collect(lambda: _run_icu_message_audit(runtime, options))

    elif stage == "reports":
        if options.output.results_dir:
            _collect_reports(lambda: _run_report_aggregator(runtime, options))

    elif stage == "autofix":
        _collect(lambda: _run_autofix(runtime, options))

    elif stage == "ai-review":
        if not options.ai_review.enabled:
            logger.info("AI Review is disabled. Set ai_review.enabled: true in config.")
        else:
             _collect(lambda: _run_ai_review(runtime, options, ai_provider=ai_provider))

    else:
        # Fallback for unknown stages or stages handled differently
        pass

    return issues, reports


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_engine(
    runtime,
    options: AuditOptions,
    ai_provider=None,
) -> tuple[list[AuditIssue], list[ReportArtifact]]:
    """Execute ``options.stage`` using *runtime* and return collected results.

    Parameters
    ----------
    runtime:
        A fully loaded :class:`~core.audit_runtime.AuditPaths` instance.
    options:
        The :class:`AuditOptions` controlling this run.
    ai_provider:
        Optional :class:`~l10n_audit.core.ai_protocol.AIProvider` implementation.
        Defaults to :class:`~l10n_audit.core.ai_http_provider.HttpAIProvider`.

    Returns
    -------
    issues : list[AuditIssue]
    reports : list[ReportArtifact]
    """
    if ai_provider is None and options.ai_review.enabled:
        from l10n_audit.core.ai_http_provider import HttpAIProvider
        ai_provider = HttpAIProvider()

    logger.info("Engine starting stage=%s results_dir=%s", options.stage, options.output.results_dir)
    issues, reports = _dispatch_stage(options.stage, runtime, options, ai_provider)
    logger.info("Engine done: %d issues, %d report artifacts", len(issues), len(reports))
    return issues, reports
