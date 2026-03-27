"""
Public Python API for the L10n Audit Toolkit.

This module exposes three top-level functions:

- :func:`run_audit` — run an audit stage and return an :class:`~l10n_audit.models.AuditResult`
- :func:`init_workspace` — initialise a workspace (equivalent to ``l10n-audit init``)
- :func:`doctor_workspace` — return a stable structured status report

All functions are safe to call from any Python thread.  No ``subprocess`` is
used internally; all audit logic runs in-process.

Example::

    from l10n_audit import run_audit, doctor_workspace

    result = run_audit("/path/to/project", stage="fast")
    print(result.summary.missing_keys)
    print(result.to_json())
"""
from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from l10n_audit.exceptions import AuditError, InvalidProjectError
from l10n_audit.models import (
    AIReview,
    AuditIssue,
    AuditOptions,
    AuditResult,
    AuditRules,
    AuditSummary,
    OutputOptions,
    ProjectDetection,
    ReportArtifact,
)
from l10n_audit.core.results_manager import manage_previous_results

logger = logging.getLogger("l10n_audit.api")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stage_module_names(stage: str, ai_enabled: bool = False) -> list[str]:
    """Return the module names that will run for a given *stage*.

    Used by the CLI to print progress messages like ``Running audits.X...``
    that match the old subprocess-based dispatch output exactly.
    """
    fast = [
        "audits.l10n_audit_pro",
        "audits.en_locale_qc",
        "audits.ar_locale_qc",
        "audits.ar_semantic_qc",
        "audits.placeholder_audit",
        "audits.terminology_audit",
    ]
    mapping: dict[str, list[str]] = {
        "fast": fast + ["reports.report_aggregator"],
        "full": fast + ["audits.icu_message_audit", "audits.en_grammar_audit", "reports.report_aggregator"],
        "grammar": ["audits.en_grammar_audit"],
        "terminology": ["audits.terminology_audit"],
        "placeholders": ["audits.placeholder_audit"],
        "ar-qc": ["audits.ar_locale_qc"],
        "ar-semantic": ["audits.ar_semantic_qc"],
        "icu": ["audits.icu_message_audit"],
        "reports": ["reports.report_aggregator"],
        "autofix": ["fixes.apply_safe_fixes"],
        "ai-review": ["audits.ai_review"],
    }
    
    modules = mapping.get(stage, [])
    
    # If AI is enabled, append ai_review to the pipeline (continuous flow)
    if ai_enabled and "audits.ai_review" not in modules:
        modules = list(modules)
        # Avoid double-adding if report_aggregator is at the end, insert after it or just append
        modules.append("audits.ai_review")
        
    return modules


def check_prerequisites() -> None:
    """Check if system prerequisites (like Java) are installed.

    Raises
    ------
    RuntimeError
        If Java is not found, with instructions for the user.
    """
    import subprocess
    try:
        # Check for Java presence
        subprocess.run(["java", "-version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError(
            "Java is required for grammar and style checks (LanguageTool).\n"
            "Please ensure Java (JRE 8 or higher) is installed and available in your PATH.\n"
            "You can download it from: https://www.java.com/"
        )


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------

def run_audit(
    project_path: str | Path,
    *,
    stage: str = "full",
    ai_enabled: bool | None = None,
    ai_api_key: str | None = None,
    ai_model: str | None = None,
    ai_api_base: str | None = None,
    ai_provider: str | None = None,
    ai_api_key_env: str | None = None,
    write_reports: bool = True,
    output_dir: str | Path | None = None,
    ai_provider_override: Any = None,
    apply_safe_fixes: bool | None = None,
    results_retention_mode: Literal["archive", "overwrite"] | None = None,
    results_retention_prefix: str | None = None,
    glossary_path: str | Path | None = None,
    out_xlsx: str | Path | None = None,
    config_schema: str | Path | None = None,
    verbose: bool = False,
    force: bool = False,
    translate_missing: bool = False,
    input_report: str | Path | None = None,
) -> AuditResult:
    """Run an audit stage on *project_path* and return structured results.

    Parameters
    ----------
    project_path:
        Absolute or relative path to the project root.
    stage:
        Audit stage to run.
    ai_enabled:
        Override AI review enablement.
    ai_api_key:
        Personal API key override.
    ai_model:
        Model name, e.g. "gpt-4o-mini" or "deepseek-chat".
    ai_api_base:
        Override provider URL.
    write_reports:
        Generate output files (JSON/CSV/XLSX).
    glossary_path:
        Path to a custom glossary JSON file.
    out_xlsx:
        Direct override path for the Excel report.
    verbose:
        Enable detailed step-by-step logging.
    force:
        Bypass safety pipelines or protection guards.

    Raises
    ------
    InvalidProjectError
        If *project_path* does not exist or is not a valid project.
    StageError
        If *stage* is not a recognised audit stage.
    AIConfigError
        If AI is enabled but the API key is missing.
    """
    check_prerequisites()

    from l10n_audit.core.validators import (
        validate_ai_config,
        validate_project_path,
        validate_stage,
    )
    from l10n_audit.core.engine import run_engine

    result = AuditResult(
        project_path=str(project_path),
        stage=stage,
    )
    result.mark_started()

    try:
        path = validate_project_path(project_path)
        validate_stage(stage)

        # Load runtime environment
        from l10n_audit.core.audit_runtime import load_runtime, AuditRuntimeError, write_json
        from l10n_audit.core.workspace import prepare_audit_workspace
        try:
            runtime = load_runtime_from_path(path)
            # Recovery & Enhancement: Create isolated workspace (replaces paths in runtime)
            runtime = prepare_audit_workspace(runtime)
            logger.info("Audit workspace prepared and runtime paths isolated.")
        except AuditRuntimeError as exc:
            raise InvalidProjectError(f"Invalid project configuration: {exc}") from exc
        
        result.profile = getattr(runtime, "project_profile", "")

        # Merge arguments with runtime config for v1.2.2 namespaced structure
        effective_ai_enabled = ai_enabled if ai_enabled is not None else runtime.ai_review["enabled"]
        effective_apply_safe_fixes = apply_safe_fixes if apply_safe_fixes is not None else runtime.output["apply_safe_fixes"]
        
        validate_ai_config(
            ai_enabled=effective_ai_enabled,
            ai_api_key=ai_api_key,
            ai_model=ai_model,
            ai_api_base=ai_api_base,
            ai_provider=ai_provider or runtime.ai_review["provider"],
            ai_api_key_env=ai_api_key_env or runtime.ai_review["api_key_env"],
        )

        options = AuditOptions(
            stage=stage,
            project_detection=ProjectDetection(
                auto_detect=True,
                force_profile=getattr(runtime, "project_profile", ""),
            ),
            audit_rules=AuditRules(
                role_identifiers=list(runtime.role_identifiers),
                entity_whitelist={k: list(v) for k, v in runtime.entity_whitelist.items()},
                apply_safe_fixes=effective_apply_safe_fixes,
                latin_whitelist=list(getattr(runtime, "latin_whitelist", [])),
            ),
            ai_review=AIReview(
                enabled=effective_ai_enabled or translate_missing,
                provider=ai_provider or runtime.ai_review["provider"],
                model=ai_model or runtime.ai_review["model"],
                api_key_env=ai_api_key_env or runtime.ai_review["api_key_env"],
                batch_size=runtime.ai_review["batch_size"],
                short_label_threshold=runtime.ai_review["short_label_threshold"],
                translate_missing=translate_missing,
            ),
            output=OutputOptions(
                results_dir=output_dir or runtime.results_dir,
                retention_mode=results_retention_mode or runtime.output.get("retention_mode", "overwrite"),
                archive_name_prefix=results_retention_prefix or runtime.output.get("archive_name_prefix", "audit"),
            ),
            # Power-user Artifact Overrides
            glossary_file=glossary_path or runtime.glossary_file,
            out_xlsx=out_xlsx,
            config_schema=config_schema,
            verbose=verbose,
            ai_provider_override=ai_provider_override,
            input_report=input_report,
        )

        # Step 2: Results Retention Management (Suicide Loop Prevention)
        from l10n_audit.models import PRODUCER_STAGES, CONSUMER_STAGES
        results_dir = options.effective_output_dir(runtime.results_dir)
        
        # Guard logic: Bypass if 'force' is enabled
        if force:
            logger.info("Force flag enabled. Bypassing stage-safety guards.")
            manage_previous_results(results_dir, options)
        elif stage in PRODUCER_STAGES:
            # Producers can safely rotate results
            manage_previous_results(results_dir, options)
        elif stage in CONSUMER_STAGES:
            # Consumers process existing findings.
            # v1.3.1 fix: We now allow these stages to proceed even if the aggregate report 
            # is missing, as they can still process individual JSON reports from per_tool/
            report_path = results_dir / "final_audit_report.json"
            if not report_path.exists():
                logger.info("Consumer stage '%s': Aggregated report not found at %s. Proceeding with per-tool cache files.", stage, report_path)
            else:
                logger.info("Consumer stage '%s' validated. Input found at %s", stage, report_path)
        else:
            # Fallback for unrecognized/adhoc stages
            manage_previous_results(results_dir, options)

        # Step 3: Produce results and reports
        issues, reports = run_engine(runtime, options, ai_provider=ai_provider_override)

        # Step 4: Unified Fix Generation (v1.3.0)
        # This replaces the old glossary-only fix logic with a unified plan
        from l10n_audit.fixes.apply_safe_fixes import build_fix_plan
        from l10n_audit.fixes.fix_merger import merge_and_export_fixes, export_review_queue
        
        issue_dicts = [i.to_dict() if hasattr(i, "to_dict") else i for i in issues]
        fix_plan = build_fix_plan(issue_dicts, runtime.project_root)
        
        # Save the full plan for future reference (internal)
        fixes_dir = results_dir / "fixes"
        fixes_dir.mkdir(parents=True, exist_ok=True)
        write_json({"plan": fix_plan}, fixes_dir / "fix_plan.json")
        
        # 4.1 Export Review Queue if any manual review is needed
        review_required = [i for i in fix_plan if i["classification"] == "review_required"]
        if review_required:
            review_xlsx = results_dir / "review" / "review_queue.xlsx"
            export_review_queue(fix_plan, runtime, review_xlsx)
            logger.info(f"Review Required: {len(review_required)} items added to {review_xlsx}")
            print(f"📝 [REVIEW QUEUE]: {len(review_required)} items need manual approval in {review_xlsx}")
            
        # 4.2 Immediate Auto-Fix Generation (.fix files next to originals)
        if effective_apply_safe_fixes:
            auto_fixes_en = {i["key"]: i["candidate_value"] for i in fix_plan if i["classification"] == "auto_safe" and i["locale"] == "en"}
            auto_fixes_ar = {i["key"]: i["candidate_value"] for i in fix_plan if i["classification"] == "auto_safe" and (i["locale"] == "ar" or i["locale"] == runtime.target_locales[0])}
            
            if auto_fixes_en and runtime.original_en_file:
                merge_and_export_fixes(runtime.original_en_file, auto_fixes_en, runtime=runtime)
            if auto_fixes_ar and runtime.original_ar_file:
                merge_and_export_fixes(runtime.original_ar_file, auto_fixes_ar, runtime=runtime)
            
            total_auto = len(auto_fixes_en) + len(auto_fixes_ar)
            if total_auto > 0:
                print(f"✅ [AUTO-FIXED]: {total_auto} safe corrections generated in .fix files.")

        result.issues = issues
        result.reports = reports
        result.summary = AuditSummary.from_issues(issues)
        # Populate total_keys from locale data (best effort)
        try:
            from l10n_audit.core.audit_runtime import load_locale_mapping
            en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
            ar_data = load_locale_mapping(runtime.ar_file, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
            result.summary.total_keys_en = len(en_data)
            result.summary.total_keys_ar = len(ar_data)
        except Exception:
            pass

    except AuditError:
        raise
    except Exception as exc:
        result.success = False
        result.error_message = str(exc)
        logger.exception("Unexpected error during audit: %s", exc)

    result.mark_finished()
    logger.info(
        "run_audit done: stage=%s issues=%d duration=%dms",
        stage, len(result.issues), result.duration_ms,
    )
    return result


def load_runtime_from_path(project_path: Path):
    """Load AuditPaths for *project_path* by temporarily changing the process
    working directory to the project root.

    This is a thin wrapper around :func:`core.audit_runtime.load_runtime` that
    sets the project root correctly without forking a subprocess.
    """
    import os
    from l10n_audit.core.audit_runtime import load_runtime

    old_cwd = os.getcwd()
    try:
        os.chdir(project_path)
        runtime = load_runtime(str(project_path / ".l10n-audit" / "cli.py"), validate=True)
    finally:
        os.chdir(old_cwd)
    return runtime


# ---------------------------------------------------------------------------
# init_workspace
# ---------------------------------------------------------------------------

def init_workspace(
    project_path: str | Path,
    *,
    force: bool = False,
    channel: str = "stable",
) -> dict[str, Any]:
    """Initialise a workspace in *project_path*.

    Parameters
    ----------
    project_path:
        Directory in which to create ``.l10n-audit/``.
    force:
        Overwrite existing workspace.
    channel:
        Template channel to use.

    Returns
    -------
    dict
        ``{"success": bool, "message": str, "workspace_dir": str}``

    Raises
    ------
    InvalidProjectError
        If *project_path* is not a valid directory.
    """
    from l10n_audit.core.validators import validate_project_path
    path = validate_project_path(project_path)

    import os
    from l10n_audit.core.workspace import init_workspace as _init_ws
    old_cwd = os.getcwd()
    try:
        os.chdir(path)
        _result = _init_ws(str(path), force=force, channel=channel)
    finally:
        os.chdir(old_cwd)

    workspace_dir = path / ".l10n-audit"
    return {
        "success": True,
        "message": "Workspace initialised successfully.",
        "workspace_dir": str(workspace_dir),
        "project_path": str(path),
    }


# ---------------------------------------------------------------------------
# doctor_workspace
# ---------------------------------------------------------------------------

def doctor_workspace(project_path: str | Path) -> dict[str, Any]:
    """Return a structured status report for *project_path*.

    The returned dict has a stable schema suitable for consumption by HTTP APIs:

    .. code-block:: json

        {
            "success": true,
            "project_path": "/abs/path",
            "framework": "flutter",
            "profile": "flutter_arb",
            "source_locale": "en",
            "target_locales": ["ar"],
            "translation_paths": {
                "en": "/abs/path/lib/l10n/intl_en.arb",
                "ar": "/abs/path/lib/l10n/intl_ar.arb"
            },
            "warnings": [],
            "errors": []
        }

    Parameters
    ----------
    project_path:
        Path to the project root.

    Returns
    -------
    dict
        Stable status schema. ``success`` will be ``false`` if errors are found.

    Raises
    ------
    InvalidProjectError
        If *project_path* does not exist.
    """
    from l10n_audit.core.validators import validate_project_path
    path = validate_project_path(project_path)

    warnings: list[str] = []
    errors: list[str] = []

    profile = ""
    framework = ""
    source_locale = ""
    target_locales: list[str] = []
    translation_paths: dict[str, str] = {}

    try:
        runtime = load_runtime_from_path(path)
        profile = getattr(runtime, "project_profile", "")
        framework = _infer_framework(profile)
        source_locale = getattr(runtime, "source_locale", "")
        target_locales = list(getattr(runtime, "target_locales", []))

        # Translation file presence checks
        if hasattr(runtime, "en_file"):
            if runtime.en_file.exists():
                translation_paths[source_locale or "en"] = str(runtime.en_file)
            else:
                errors.append(f"Source locale file not found: {runtime.en_file}")

        if hasattr(runtime, "ar_file"):
            target_locale = target_locales[0] if target_locales else "ar"
            if runtime.ar_file.exists():
                translation_paths[target_locale] = str(runtime.ar_file)
            else:
                errors.append(f"Target locale file not found: {runtime.ar_file}")

        # Config file check
        config_path = path / ".l10n-audit" / "config" / "config.json"
        if not config_path.exists():
            warnings.append(f"Config file not found at {config_path}. Run 'l10n-audit init' first.")

        # Glossary check
        if hasattr(runtime, "glossary_file") and not runtime.glossary_file.exists():
            warnings.append(f"Glossary file not found: {runtime.glossary_file}")

    except Exception as exc:
        errors.append(f"Failed to load project runtime: {exc}")

    success = len(errors) == 0
    return {
        "success": success,
        "project_path": str(path),
        "framework": framework,
        "profile": profile,
        "source_locale": source_locale,
        "target_locales": target_locales,
        "translation_paths": translation_paths,
        "warnings": warnings,
        "errors": errors,
    }





def _infer_framework(profile: str) -> str:
    """Map a profile string to a user-friendly framework name."""
    _map = {
        "flutter_arb": "flutter",
        "react_i18n": "react",
        "laravel_php": "laravel",
        "json_flat": "json",
        "vue_i18n": "vue",
        "android_xml": "android",
        "ios_strings": "ios",
    }
    return _map.get(profile, profile)
