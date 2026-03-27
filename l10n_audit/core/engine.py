"""
محرك التدقيق الأساسي (Core Engine) — يقوم بتنسيق وتنفيذ مراحل التدقيق المختلفة.

شرح مراحل التدقيق (Stages):
1. fast (التدقيق السريع): يركز على الفحوصات اللغوية والتقنية الأساسية؛ مناسب للاستخدام اليومي 
   أثناء التطوير للتأكد من سلامة المتغيرات والقواميس.
2. full (التدقيق الشامل): يتضمن جميع فحوصات المرحلة السريعة بالإضافة إلى فحص القواعد النحوية 
   (Grammar Audit) باستخدام LanguageTool، وفحص رسائل ICU المعقدة.
3. ai-review (المراجعة بالذكاء الاصطناعي): مرحلة اختيارية تستخدم النماذج اللغوية (LLMs) 
   لاقتراح ترجمات للمفاتيح المفقودة أو تحسين صياغة النصوص الحالية بناءً على السياق.
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
    from l10n_audit.audits.l10n_audit_pro import run_stage
    return run_stage(runtime, options)


def _run_en_locale_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.en_locale_qc import run_stage
    return run_stage(runtime, options)


def _run_ar_locale_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.ar_locale_qc import run_stage
    return run_stage(runtime, options)


def _run_ar_semantic_qc(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.ar_semantic_qc import run_stage
    return run_stage(runtime, options)


def _run_placeholder_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.placeholder_audit import run_stage
    return run_stage(runtime, options)


def _run_terminology_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.terminology_audit import run_stage
    return run_stage(runtime, options)


def _run_icu_message_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.icu_message_audit import run_stage
    return run_stage(runtime, options)


def _run_en_grammar_audit(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.audits.en_grammar_audit import run_stage
    return run_stage(runtime, options)


def _run_ai_review(runtime, options: AuditOptions, ai_provider=None, previous_issues=None) -> list[AuditIssue]:
    from l10n_audit.audits.ai_review import run_stage
    return run_stage(runtime, options, ai_provider=ai_provider, previous_issues=previous_issues)


def _run_report_aggregator(runtime, options: AuditOptions, **kwargs) -> list[ReportArtifact]:
    from l10n_audit.reports.report_aggregator import run_stage
    return run_stage(runtime, options, **kwargs)


def _run_autofix(runtime, options: AuditOptions) -> list[AuditIssue]:
    from l10n_audit.fixes.apply_safe_fixes import run_stage
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

    def _collect(fns):
        if not fns:
            return
        print(f"\n🧪 Running {len(fns)} Linguistic Audits:", end="", flush=True)
        for name, fn in fns:
            print(f" {name}⏳", end="", flush=True)
            try:
                result = fn()
                if result:
                    issues.extend(result)
                print("\b\b\b✅ ", end="", flush=True)
            except Exception as exc:
                print("\b\b\b❌ ", end="", flush=True)
                logger.warning("Stage sub-step %s failed: %s", name, exc)
                issues.append(
                    AuditIssue(
                        key="ENGINE_FAILURE",
                        code="ENGINE_ERROR",
                        issue_type="engine_error",
                        severity="error",
                        message=f"Audit stage sub-step {name} failed: {exc}",
                    )
                )
        print("Done.")

    def _collect_reports(*fns):
        for fn in fns:
            try:
                result = fn()
                if result:
                    reports.extend(result)
            except Exception as exc:
                logger.warning("Report step failed: %s", exc)

    if stage == "fast":
        print("🔍 Scanning source code and locale files...", end="", flush=True)
        # We manually add some dots to simulate scanning folders
        import time as _time
        for _ in range(3):
            _time.sleep(0.1)
            print(".", end="", flush=True)
        print(" Done.")

        _collect([
            ("L10n Pro", lambda: _run_l10n_audit_pro(runtime, options)),
            ("EN Locale QC", lambda: _run_en_locale_qc(runtime, options)),
            ("AR Locale QC", lambda: _run_ar_locale_qc(runtime, options)),
            ("AR Semantic QC", lambda: _run_ar_semantic_qc(runtime, options)),
            ("Placeholders", lambda: _run_placeholder_audit(runtime, options)),
            ("Terminology", lambda: _run_terminology_audit(runtime, options)),
        ])
        
        # Continuous Pipeline: If AI is enabled, run it BEFORE reporting so its findings are included
        current_sources = _FAST_SOURCES
        if options.ai_review.enabled:
            _collect([("AI Review", lambda: _run_ai_review(runtime, options, ai_provider=ai_provider, previous_issues=issues))])
            current_sources += ",ai_review"

        if options.write_reports:
            print(f"📊 Generating final artifacts and reports...", end="", flush=True)
            _collect_reports(lambda: _run_report_aggregator(runtime, options, sources=current_sources))
            print(f" Done. 📍 Path: {options.effective_output_dir(runtime.results_dir)}")

    elif stage == "full":
        print("🔍 Scanning source code and locale files...", end="", flush=True)
        import time as _time
        for _ in range(5):
            _time.sleep(0.1)
            print(".", end="", flush=True)
        print(" Done.")

        _collect([
            ("L10n Pro", lambda: _run_l10n_audit_pro(runtime, options)),
            ("EN Locale QC", lambda: _run_en_locale_qc(runtime, options)),
            ("AR Locale QC", lambda: _run_ar_locale_qc(runtime, options)),
            ("AR Semantic QC", lambda: _run_ar_semantic_qc(runtime, options)),
            ("Placeholders", lambda: _run_placeholder_audit(runtime, options)),
            ("Terminology", lambda: _run_terminology_audit(runtime, options)),
            ("ICU Messages", lambda: _run_icu_message_audit(runtime, options)),
            ("EN Grammar", lambda: _run_en_grammar_audit(runtime, options)),
        ])
            
        # Continuous Pipeline: If AI is enabled, run it BEFORE reporting so its findings are included
        current_sources = _FULL_SOURCES
        if options.ai_review.enabled:
            _collect([("AI Review", lambda: _run_ai_review(runtime, options, ai_provider=ai_provider, previous_issues=issues))])
            current_sources += ",ai_review"

        if options.write_reports:
            print(f"📊 Generating final artifacts and reports...", end="", flush=True)
            _collect_reports(lambda: _run_report_aggregator(runtime, options, sources=current_sources))
            print(f" Done. 📍 Path: {options.effective_output_dir(runtime.results_dir)}")

    elif stage == "grammar":
        _collect([("EN Grammar", lambda: _run_en_grammar_audit(runtime, options))])

    elif stage == "terminology":
        _collect([("Terminology", lambda: _run_terminology_audit(runtime, options))])

    elif stage == "placeholders":
        _collect([("Placeholders", lambda: _run_placeholder_audit(runtime, options))])

    elif stage == "ar-qc":
        _collect([("AR Locale QC", lambda: _run_ar_locale_qc(runtime, options))])

    elif stage == "ar-semantic":
        _collect([("AR Semantic QC", lambda: _run_ar_semantic_qc(runtime, options))])

    elif stage == "icu":
        _collect([("ICU Messages", lambda: _run_icu_message_audit(runtime, options))])

    elif stage == "reports":
        if options.output.results_dir:
            print(f"📊 Generating final artifacts and reports...", end="", flush=True)
            _collect_reports(lambda: _run_report_aggregator(runtime, options))
            print(f" Done. 📍 Path: {options.effective_output_dir(runtime.results_dir)}")

    elif stage == "autofix":
        _collect([("Autofix", lambda: _run_autofix(runtime, options))])

    elif stage == "ai-review":
        if not options.ai_review.enabled:
            logger.info("AI Review is disabled. Set ai_review.enabled: true in config.")
        else:
             _collect([("AI Review", lambda: _run_ai_review(runtime, options, ai_provider=ai_provider))])

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
        # UX: Reassurance for the user
        print("✨ AI Configuration loaded successfully.")

    if options.ai_review.enabled:
        logger.debug("AI Review active. Using keys from global home (~/.l10n-audit/config.env)")

    logger.info("Engine starting stage=%s results_dir=%s", options.stage, options.output.results_dir)
    issues, reports = _dispatch_stage(options.stage, runtime, options, ai_provider)
    logger.info("Engine done: %d issues, %d report artifacts", len(issues), len(reports))
    return issues, reports
