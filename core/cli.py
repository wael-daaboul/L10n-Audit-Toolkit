from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from core.workspace import (
    find_project_root,
    init_workspace,
    toolkit_version,
    update_workspace,
    workspace_config_path,
    workspace_status,
)


# ---------------------------------------------------------------------------
# Legacy subprocess-based dispatch (kept as fallback)
# ---------------------------------------------------------------------------

def _run_module(module: str, args: list[str], config_path: Path) -> None:
    env = os.environ.copy()
    env["L10N_AUDIT_CONFIG"] = str(config_path)
    subprocess.run([sys.executable, "-m", module, *args], check=True, env=env)


def _stage_modules(stage: str) -> list[tuple[str, list[str]]]:
    fast = [
        ("audits.l10n_audit_pro", []),
        ("audits.en_locale_qc", []),
        ("audits.ar_locale_qc", []),
        ("audits.ar_semantic_qc", []),
        ("audits.placeholder_audit", []),
        ("audits.terminology_audit", []),
    ]
    mapping = {
        "fast": fast + [
            ("reports.report_aggregator", ["--sources", "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders"]),
        ],
        "full": fast + [
            ("audits.icu_message_audit", []),
            ("audits.en_grammar_audit", []),
            ("reports.report_aggregator", ["--sources", "localization,locale_qc,ar_locale_qc,ar_semantic_qc,terminology,placeholders,icu_message_audit,grammar"]),
        ],
        "grammar": [("audits.en_grammar_audit", [])],
        "terminology": [("audits.terminology_audit", [])],
        "placeholders": [("audits.placeholder_audit", [])],
        "ar-qc": [("audits.ar_locale_qc", [])],
        "ar-semantic": [("audits.ar_semantic_qc", [])],
        "icu": [("audits.icu_message_audit", [])],
        "reports": [("reports.report_aggregator", [])],
        "autofix": [("fixes.apply_safe_fixes", [])],
        "ai-review": [("audits.ai_review", [])],
    }
    return mapping[stage]


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.path or Path.cwd()))
    result = init_workspace(
        project_root,
        force=args.force,
        channel=args.channel,
        from_github=args.from_github,
        repo=args.repo,
    )
    print(f"Initialized workspace: {result['workspace_dir']}")
    print(f"Detected profile: {result['profile_name']}")
    print(f"Config: {result['config_path']}")
    print(f"Glossary: {result['glossary_path']}")
    score = int(result["detection"].get("score", 0))
    if score:
        print(f"Detection score: {score}")
    if result.get("github_sync"):
        print(f"GitHub templates: {result['github_sync']['template_dir']}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.path or Path.cwd()))
    status = workspace_status(project_root)
    print(f"Project root: {status['project_root']}")
    print(f"Workspace: {status['workspace_dir']}")
    print(f"Workspace exists: {'yes' if status['workspace_exists'] else 'no'}")
    print(f"Config exists: {'yes' if status['config_exists'] else 'no'}")
    print(f"Glossary exists: {'yes' if status['glossary_exists'] else 'no'}")
    print(f"Detected profile: {status['detected_profile']}")
    score = int(status['detection'].get('score', 0))
    print(f"Detection score: {score}")
    candidates = status['detection'].get('candidates', [])
    if candidates:
        print("Top candidates:")
        for item in candidates[:3]:
            print(f"- {item['profile']}: {item['score']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run an audit stage.

    Attempts to use the in-process engine via :func:`l10n_audit.run_audit` for
    speed and structured output.  Falls back to the legacy subprocess dispatch
    if the ``l10n_audit`` package is not importable.

    All CLI flags and exit codes are preserved: returns 0 on successful
    completion regardless of how many issues were found (matching the original
    CLI contract). Only returns non-zero on actual errors / crashes.
    """
    project_root = find_project_root(Path(args.path or Path.cwd()))
    config_path = workspace_config_path(project_root)
    if not config_path.exists():
        init_workspace(project_root, force=False)

    stage = args.stage

    try:
        import l10n_audit
        from l10n_audit.api import _stage_module_names  # progress labels

        for label in _stage_module_names(stage):
            print(f"Running {label}...")

        result = l10n_audit.run_audit(
            project_root,
            stage=stage,
            ai_enabled=getattr(args, "ai_enabled", False),
            ai_api_key=getattr(args, "ai_api_key", None),
            ai_model=getattr(args, "ai_model", None),
            ai_api_base=getattr(args, "ai_api_base", None),
            write_reports=True,
            apply_safe_fixes=getattr(args, "apply_safe_fixes", False),
            results_retention_mode=getattr(args, "retention_mode", None),
            results_retention_prefix=getattr(args, "retention_prefix", None),
        )

        if not result.success:
            print(f"Audit failed: {result.error_message}", file=sys.stderr)
            return 1

        summary = result.summary
        print(f"\nAudit complete — stage: {stage}")
        print(f"   Total issues     : {summary.total_issues}")
        print(f"   Missing keys     : {summary.missing_keys}")
        print(f"   Unused keys      : {summary.unused_keys}")
        print(f"   Empty transl.    : {summary.empty_translations}")
        print(f"   Placeholder err  : {summary.placeholder_errors}")
        print(f"   Terminology      : {summary.terminology_errors}")
        print(f"   AR QC issues     : {summary.ar_qc_issues}")
        if result.reports:
            print(f"   Reports          : {len(result.reports)} file(s)")
        if result.duration_ms:
            print(f"   Duration         : {result.duration_ms} ms")
        return 0

    except ImportError:
        # Fallback: legacy subprocess dispatch
        for module, module_args in _stage_modules(stage):
            print(f"Running {module}...")
            curr_args = list(module_args)
            if module == "audits.ai_review":
                if getattr(args, "ai_enabled", False):
                    curr_args.append("--ai-enabled")
                if getattr(args, "ai_api_key", None):
                    curr_args.extend(["--ai-api-key", args.ai_api_key])
                if getattr(args, "ai_api_base", None):
                    curr_args.extend(["--ai-api-base", args.ai_api_base])
                if getattr(args, "ai_model", None):
                    curr_args.extend(["--ai-model", args.ai_model])
            _run_module(module, curr_args, config_path)
        return 0


def cmd_update(args: argparse.Namespace) -> int:
    project_root = find_project_root(Path(args.path or Path.cwd()))
    if args.check:
        status = workspace_status(project_root)
        print(f"Workspace: {status['workspace_dir']}")
        print(f"Detected profile: {status['detected_profile']}")
        print(f"Toolkit version: {toolkit_version()}")
        return 0
    result = update_workspace(project_root, channel=args.channel, from_github=args.from_github, repo=args.repo)
    print(f"Updated workspace: {result['workspace_dir']}")
    print(f"Config: {result['config_path']}")
    backup = result.get("backup_path")
    if backup:
        print(f"Backup: {backup}")
    if result.get("github_sync"):
        print(f"GitHub templates: {result['github_sync']['template_dir']}")
    return 0


def cmd_self_update(_args: argparse.Namespace) -> int:
    print("If you installed the launcher with pipx, run:")
    print("pipx upgrade l10n-audit-toolkit")
    print("If you installed from GitHub directly, run:")
    print("pipx upgrade --include-injected l10n-audit-toolkit")
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="l10n-audit")
    parser.add_argument("--version", action="version", version=f"l10n-audit-toolkit {toolkit_version()}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a local .l10n-audit workspace")
    init_parser.add_argument("--path", default=".")
    init_parser.add_argument("--force", action="store_true")
    init_parser.add_argument("--channel", default="stable", choices=["stable", "main"])
    init_parser.add_argument("--from-github", action="store_true")
    init_parser.add_argument("--repo", default="")
    init_parser.set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser("run", help="Run audits using the local workspace config")
    run_parser.add_argument("--path", default=".")
    run_parser.add_argument(
        "--stage", default="full",
        choices=["fast", "full", "grammar", "terminology", "placeholders", "ar-qc", "ar-semantic", "icu", "reports", "autofix", "ai-review"],
    )
    run_parser.add_argument("--ai-enabled", action="store_true", help="Enable AI review features (opt-in)")
    run_parser.add_argument("--ai-api-key", help="API Key for AI provider")
    run_parser.add_argument("--ai-api-base", help="Custom API Base URL (OpenAI-compatible)")
    run_parser.add_argument("--ai-model", help="AI Model to use")
    run_parser.add_argument("--apply-safe-fixes", action="store_true", help="Automatically apply terminology fixes after audit.")
    run_parser.add_argument("--retention-mode", choices=["archive", "overwrite"], help="How to handle previous Results/ (archive or overwrite)")
    run_parser.add_argument("--retention-prefix", help="Prefix for archive folders (default: 'audit')")
    run_parser.set_defaults(func=cmd_run)

    doctor_parser = subparsers.add_parser("doctor", help="Inspect project and workspace discovery")
    doctor_parser.add_argument("--path", default=".")
    doctor_parser.set_defaults(func=cmd_doctor)

    update_parser = subparsers.add_parser("update", help="Refresh an existing local workspace")
    update_parser.add_argument("--path", default=".")
    update_parser.add_argument("--check", action="store_true")
    update_parser.add_argument("--channel", default="stable", choices=["stable", "main"])
    update_parser.add_argument("--from-github", action="store_true")
    update_parser.add_argument("--repo", default="")
    update_parser.set_defaults(func=cmd_update)

    self_update_parser = subparsers.add_parser("self-update", help="Show how to update the global launcher")
    self_update_parser.set_defaults(func=cmd_self_update)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
