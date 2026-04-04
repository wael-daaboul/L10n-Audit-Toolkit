from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from l10n_audit.core.workspace import (
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
    print(f"Workspace   : {status['workspace_dir']}")
    print(f"Framework   : {status['detected_profile']}")
    
    from l10n_audit.core.utils import check_java_available
    java_ok = check_java_available()
    print(f" - Workspace exists : {'✅ yes' if status['workspace_exists'] else '❌ no'}")
    print(f" - Config exists    : {'✅ yes' if status['config_exists'] else '❌ no'}")
    print(f" - Glossary exists  : {'✅ yes' if status['glossary_exists'] else '⚠️ no'}")
    print(f" - Java (for LT)    : {'✅ found' if java_ok else '❌ NOT FOUND'}")
    
    if not java_ok:
        print(f"\n[Java Required for Grammar Audits]")
        print(f" LanguageTool requires a Java runtime for local execution.")
        print(f" Please install Java to enable full linguistic analysis:")
        print(f"   • macOS: brew install openjdk")
        print(f"   • Ubuntu: sudo apt install default-jre")
        print(f"   • Windows: https://adoptium.net/")
    
    # 1. Configuration Schema Validation
    if status['config_exists']:
        print(f"\n[Configuration Scan]")
        try:
            from l10n_audit.core.schema_validation import validate_file, preset_mappings
            config_json = status['config_path']
            # Find schema in same dir as cli.py
            tools_dir = Path(__file__).resolve().parent.parent
            schema_path = tools_dir / "schemas" / "config.schema.json"
            
            if schema_path.exists():
                errors = validate_file(config_json, schema_path)
                if errors:
                    print(f" ❌ Schema errors in {config_json.name}:")
                    for err in errors:
                        print(f"    - {err}")
                else:
                    print(f" ✅ config.json structure is valid.")
            else:
                print(f" ⚠️ Schema file not found: {schema_path}")
        except Exception as e:
            print(f" ⚠️ Config validation error: {e}")

    # 2. AI Dependency Guard
    if getattr(args, "check_ai", False):
        print(f"\n[AI Dependency Check]")
        litellm_ok = False
        dotenv_ok = False
        try:
            import litellm
            litellm_ok = True
            print(f" ✅ litellm: Installed ({getattr(litellm, '__version__', 'unknown')})")
        except ImportError:
            print(f" ❌ litellm: MISSING")
            
        try:
            import dotenv
            dotenv_ok = True
            print(f" ✅ python-dotenv: Installed")
        except ImportError:
            print(f" ❌ python-dotenv: MISSING")

        if not litellm_ok or not dotenv_ok:
            print(f"\n[Action Required]")
            print(f" Please inject missing dependencies into your l10n-audit environment:")
            print(f"   pipx inject l10n-audit-toolkit litellm python-dotenv")

    return 0


def get_ai_model(args, config_dict):
    """
    Resolves the AI model name from CLI args or config.
    Supports short names (shortcuts) like 'reasoner', 'chat', 'fast'.
    """
    # 1. CLI Override
    cli_model = getattr(args, "ai_model", None)
    available_models = config_dict.get("available_models", {})
    
    if cli_model in available_models:
        return available_models[cli_model]
    if cli_model:
        return cli_model
        
    # 2. Config Fallback
    config_model = config_dict.get("model")
    if config_model:
        return config_model
        
    # 3. Ultimate Default
    return "deepseek/deepseek-chat"


def cmd_run(args: argparse.Namespace) -> int:
    path_val = args.project_root if getattr(args, "project_root", None) else args.path
    project_root = find_project_root(Path(path_val).resolve())
    config_path = workspace_config_path(project_root)
    
    verbose = getattr(args, "verbose", False)
    force = getattr(args, "force", False)

    if not config_path.exists():
        if verbose:
            print(f"  [Init] No workspace found at {project_root}. Initializing...")
        init_workspace(project_root, force=False)

    stage = args.stage
    
    # Handle --reset (Manual Cache/Results Clear)
    if getattr(args, "reset", False):
        results_dir = project_root / ".l10n-audit" / "Results"
        if results_dir.exists():
            print(f"  [Reset] Clearing previous results at {results_dir}...")
            import shutil
            shutil.rmtree(results_dir)
            results_dir.mkdir(parents=True, exist_ok=True)

    try:
        import l10n_audit
        from l10n_audit.api import _stage_module_names

        if verbose:
            version = getattr(l10n_audit, '__version__', '1.5.0')
            print(f"  [Engine] L10n Audit Engine v{version} loaded.")
            print(f"  [Stage] Target: {stage}")

        # Resolve model name dynamically
        from l10n_audit.core.workspace import read_json
        config_dict = {}
        if config_path.exists():
            try:
                config_dict = read_json(config_path).get("ai_review", {})
            except Exception:
                pass
        
        resolved_model = get_ai_model(args, config_dict)
        ai_enabled = getattr(args, "ai_enabled", False)
        
        for label in _stage_module_names(stage, ai_enabled=ai_enabled):
            print(f"Running {label}...")

        # Unify arguments with the main API
        result = l10n_audit.run_audit(
            project_root,
            stage=stage,
            ai_enabled=ai_enabled,
            ai_api_key=getattr(args, "ai_api_key", None),
            ai_model=resolved_model,
            ai_api_base=getattr(args, "ai_api_base", None),
            write_reports=True,
            apply_safe_fixes=getattr(args, "apply_safe_fixes", False),
            results_retention_mode=getattr(args, "retention_mode", None),
            results_retention_prefix=getattr(args, "retention_prefix", None),
            # New Power-User Arguments
            translate_missing=getattr(args, "translate_missing", False),
            glossary_path=getattr(args, "glossary", None),
            out_xlsx=getattr(args, "out_xlsx", None),
            config_schema=getattr(args, "schema", None),
            verbose=args.verbose,
            force=args.force,
            input_report=getattr(args, "input_report", None),
        )

        if not result.success:
            print(f"\n❌ Audit failed: {result.error_message}", file=sys.stderr)
            return 1

        summary = result.summary
        print(f"\n✨ Audit complete — stage: {stage}")
        print(f"   Total issues     : {summary.total_issues}")
        print(f"   Missing keys     : {summary.missing_keys}")
        print(f"   Unused keys      : {summary.unused_keys}")
        print(f"   Empty translations: {summary.empty_translations}")
        print(f"   Placeholder errors: {summary.placeholder_errors}")
        print(f"   Terminology errors: {summary.terminology_errors}")
        print(f"   Arabic QC issues : {summary.ar_qc_issues}")
        
        if result.reports:
            print(f"   Artifacts saved  : {len(result.reports)} file(s)")
            if verbose:
                for r in result.reports:
                    print(f"     - {r.path}")
        
        if result.duration_ms:
            print(f"   Duration         : {result.duration_ms} ms")
        
        return 0

    except ImportError as e:
        if verbose:
            print(f"  [Fallback] Engine import failed: {e}. Using legacy dispatch.")
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


def cmd_self_update(args: argparse.Namespace) -> int:
    """يعرض تعليمات تحديث الأداة عبر pipx."""
    print("\n🚀 لتحديث أداة l10n-audit لآخر إصدار، نفذ الأمر التالي:")
    print("   pipx upgrade l10n-audit-toolkit\n")
    return 0


def cmd_deprecations(args: argparse.Namespace) -> int:
    """Show the Phase G1 deprecation registry status."""
    from l10n_audit.core.deprecation_registry import summary_dict
    
    sd = summary_dict()
    print("\n=== Deprecation Status ===\n")
    
    mapping = {
        "active_required": "ACTIVE",
        "compatibility_required": "COMPATIBILITY",
        "optional_legacy": "OPTIONAL LEGACY",
        "deprecated_candidate": "DEPRECATED",
        "removed": "REMOVED",
    }
    
    for class_key, title in mapping.items():
        items = sd["by_classification"].get(class_key, [])
        print(f"{title} ({len(items)})")
        for item in items:
            print(f"- {item}")
        print()
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    path_val = getattr(args, "path", ".")
    project_root = find_project_root(Path(path_val).resolve())
    
    from l10n_audit.core.audit_runtime import load_runtime
    # load_runtime will find the .l10n-audit folder starting from project_root
    runtime = load_runtime(project_root / "cli_anchor", validate=False)
    
    from l10n_audit.fixes.apply_review_fixes import run_apply
    
    # Default to .l10n-audit/Results/review/review_queue.xlsx if not provided
    review_queue = Path(args.review_queue) if args.review_queue else runtime.results_dir / "review" / "review_queue.xlsx"
    if not args.review_queue and not review_queue.exists():
        # Fallback to absolute project-root based path if runtime results_dir didn't help
        review_queue = project_root / ".l10n-audit" / "Results" / "review" / "review_queue.xlsx"
    
    if not review_queue.exists():
        print(f"❌ Error: Review queue not found at {review_queue}")
        print("   Please run an audit first or specify the path with --review-queue")
        return 1

    print(f"🛠️ Applying fixes from: {review_queue.name}")
    if args.all:
        print("🚀 Mode: --all (Merging all suggestions including AI)")
    
    report = run_apply(
        runtime,
        review_queue,
        apply_all=args.all,
        out_final_json=str(runtime.results_dir / "final_locale" / "ar.final.json"),
        out_report=str(runtime.results_dir / "final_locale" / "review_fixes_report.json")
    )
    
    print(f"\n✅ Apply complete:")
    print(f"   - Approved/All items applied: {report['summary']['approved_rows_applied']}")
    print(f"   - Items skipped (conflicts):  {report['summary']['approved_rows_skipped']}")
    
    if report['summary']['en_fixed_files'] or report['summary']['ar_fixed_files']:
        print(f"   - Result: Generated .fix files next to original locale files.")
    
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # 1. Base Parser with Global Flags
    parser = argparse.ArgumentParser(prog="l10n-audit")
    parser.add_argument("--version", action="version", version=f"l10n-audit-toolkit {toolkit_version()}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed execution logs and progress.")
    parser.add_argument("-f", "--force", action="store_true", help="Force operation (e.g., overwrite files or skip pipeline guards).")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 2. Command Parsers
    init_parser = subparsers.add_parser("init", help="Initialize a local .l10n-audit workspace")
    init_parser.add_argument("--path", default=".")
    init_parser.add_argument("--channel", default="stable", choices=["stable", "main"])
    init_parser.add_argument("--from-github", action="store_true")
    init_parser.add_argument("--repo", default="")
    init_parser.set_defaults(func=cmd_init)

    run_parser = subparsers.add_parser("run", help="Run audits using the local workspace config")
    run_parser.add_argument("--path", default=".")
    run_parser.add_argument(
        "--stage", default="full",
        choices=["fast", "full", "grammar", "terminology", "placeholders", "ar-qc", "ar-semantic", "icu", "reports", "autofix", "ai-review"],
        help="تحديد مرحلة الفحص (fast: سريع، full: شامل، ai-review: مراجعة الذكاء الاصطناعي)"
    )
    run_parser.add_argument("--ai-enabled", action="store_true", help="تفعيل مراجعة الذكاء الاصطناعي (اختياري)")
    run_parser.add_argument("--ai-api-key", help="API Key for AI provider")
    run_parser.add_argument("--ai-api-base", help="Custom API Base URL (OpenAI-compatible)")
    run_parser.add_argument("--ai-model", help="AI Model to use")
    run_parser.add_argument("--translate-missing", action="store_true", help="Auto-translate missing keys using AI")
    run_parser.add_argument("--apply-safe-fixes", action="store_true", help="Automatically apply terminology fixes after audit.")
    run_parser.add_argument("--retention-mode", choices=["archive", "overwrite"], help="How to handle previous Results/ (archive or overwrite)")
    run_parser.add_argument("--retention-prefix", help="Prefix for archive folders (default: 'audit')")
    
    # Unified 'Hidden Gems'
    run_parser.add_argument("--glossary", help="Path to a custom terminology glossary JSON.")
    run_parser.add_argument("--out-xlsx", help="Override path for the generated Excel report artifact.")
    run_parser.add_argument("--project-root", help="Explicit path to the project source root (overrides --path).")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed execution logs and progress.")
    run_parser.add_argument("-f", "--force", action="store_true", help="Force operation (e.g., overwrite files or skip pipeline guards).")
    run_parser.add_argument("--reset", action="store_true", help="Safely clear all existing results/cache before starting.")
    run_parser.add_argument("--input-report", help="Path to a previous JSON report to reload data from (for reports/autofix stages)")
    
    run_parser.set_defaults(func=cmd_run)

    doctor_parser = subparsers.add_parser("doctor", help="Inspect project and workspace discovery")
    doctor_parser.add_argument("--path", default=".")
    doctor_parser.add_argument("--check-ai", action="store_true", help="Perform pre-flight AI dependency and connection check.")
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

    apply_parser = subparsers.add_parser("apply", help="Apply approved fixes from the review queue to original files")
    apply_parser.add_argument("--path", default=".", help="Project root path")
    apply_parser.add_argument("--review-queue", help="Path to review_queue.xlsx (optional)")
    apply_parser.add_argument("--all", action="store_true", help="Force-apply all suggestions (including AI) regardless of status")
    apply_parser.set_defaults(func=cmd_apply)

    deprecations_parser = subparsers.add_parser("deprecations", help="Show the current state of legacy artifacts decommissioning.")
    deprecations_parser.set_defaults(func=cmd_deprecations)

    return parser


def main() -> None:
    from dotenv import load_dotenv
    from l10n_audit.core.workspace import ensure_global_config, get_global_config_path
    
    # 1. Ensure Global Config Home (~/.l10n-audit/config.env)
    ensure_global_config()
    
    # 2. Load GLOBAL env keys
    global_env = get_global_config_path()
    if global_env.exists():
        load_dotenv(dotenv_path=global_env)
    
    # 3. Load LOCAL .env (Overrides global if present)
    load_dotenv()
    
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
