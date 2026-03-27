from __future__ import annotations

import io
import json
import os
import shutil
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen
from zipfile import ZipFile

from l10n_audit.core.audit_runtime import _load_project_profiles, detect_tools_dir
from l10n_audit.core.profile_detection import LOW_CONFIDENCE_THRESHOLD, autodetect_profile

WORKSPACE_DIRNAME = ".l10n-audit"
WORKSPACE_CONFIG = "config.json"
WORKSPACE_VERSION = "version.json"
WORKSPACE_GLOSSARY = "glossary.json"
WORKSPACE_TEMPLATE_DIR = "toolkit-template"
WORKSPACE_RUN_DIR = "workspace" # Isolation folder for active runs
CURRENT_CONFIG_VERSION = 2


def get_global_config_path() -> Path:
    """Return the absolute path to the global config file (~/.l10n-audit/config.env)."""
    return Path.home() / ".l10n-audit" / "config.env"


def ensure_global_config() -> None:
    """Check if the global config directory and file exist. 
    If not, create them with a template and print a welcome message.
    """
    config_path = get_global_config_path()
    if not config_path.exists():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            template = (
                "# L10n Audit - Global AI Configuration\n"
                "DEEPSEEK_API_KEY=\n"
                "OPENAI_API_KEY=\n"
                "ANTHROPIC_API_KEY=\n"
                "AI_API_KEY=\n"
            )
            config_path.write_text(template, encoding="utf-8")
            
            # Color codes for a premium feel
            # \033[94m (Blue), \033[92m (Green), \033[0m (Reset)
            print(f"\n\033[94m✨ Welcome! Global config created at \033[92m{config_path}\033[0m")
            print(f"\033[94m👉 Please add your API key there to enable AI features.\033[0m\n")
        except Exception:
            # Silent fail for permission issues or read-only homes
            pass


def toolkit_version() -> str:
    # Prioritize our internal source-of-truth VERSION during v1.2.2 rollout
    from l10n_audit.models import VERSION
    return VERSION


def workspace_dir(project_root: Path) -> Path:
    return project_root / WORKSPACE_DIRNAME


def workspace_config_path(project_root: Path) -> Path:
    return workspace_dir(project_root) / WORKSPACE_CONFIG


def workspace_version_path(project_root: Path) -> Path:
    return workspace_dir(project_root) / WORKSPACE_VERSION


def workspace_glossary_path(project_root: Path) -> Path:
    return workspace_dir(project_root) / WORKSPACE_GLOSSARY


def workspace_template_dir(project_root: Path) -> Path:
    return workspace_dir(project_root) / WORKSPACE_TEMPLATE_DIR


def find_project_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    markers = (
        ".git",
        "pubspec.yaml",
        "artisan",
        "package.json",
        "assets/language",
        "resources/lang",
        "lib",
        "src",
    )
    for candidate in (current, *current.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return current


def detect_project_profile(project_root: Path, tools_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    detected_tools_dir = tools_dir or detect_tools_dir(__file__)
    profiles = _load_project_profiles(detected_tools_dir / "config")
    best, ranked = autodetect_profile(project_root, None, profiles)
    details = {
        "score": best.score,
        "reasons": list(best.reasons),
        "candidates": [
            {"profile": item.profile_name, "score": item.score, "reasons": list(item.reasons[:4])}
            for item in ranked[:5]
        ],
    }
    if best.score < LOW_CONFIDENCE_THRESHOLD:
        return "unknown", details
    return best.profile_name, details


def default_workspace_config(project_root: Path, profile_name: str) -> dict[str, Any]:
    return {
        "config_version": CURRENT_CONFIG_VERSION,
        "//_comment_version": "Configuration structure version / إصدار هيكل التكوين",
        
        "project_detection": {
            "//_comment_auto": "Enable automatic framework discovery / تفعيل الاكتشاف التلقائي لإطار العمل",
            "auto_detect": True,
            "//_comment_force": "Override with a specific profile name / التجاوز باستخدام اسم ملف شخصي محدد",
            "force_profile": profile_name if profile_name != "auto" else None
        },
        
        "audit_rules": {
            "//_comment_roles": "Key identifying roles (e.g., driver, admin) / أدوار مميزة (مثل: سائق، مسؤول)",
            "role_identifiers": [],
            "//_comment_latin": "Latin words allowed in Arabic text / كلمات لاتينية مسموح بها في النصوص العربية",
            "latin_whitelist": [],
            "//_comment_entity": "Specific entities to protect from rewriting / كيانات محددة تجب حمايتها من إعادة الكتابة",
            "entity_whitelist": {"en": [], "ar": []},
            "//_comment_fix": "Apply glossary fixes automatically / تطبيق إصلاحات القاموس تلقائياً",
            "apply_safe_fixes": False
        },
        
        "ai_review": {
            "//_comment_enabled": "Enable LLM-based audit stage / تفعيل مرحلة التدقيق المعتمدة على الذكاء الاصطناعي",
            "enabled": False,
            "//_comment_provider": "AI provider (e.g., litellm) / مزود الذكاء الاصطناعي (مثل: litellm)",
            "provider": "litellm",
            "//_comment_model": "Model identifier / معرف النموذج",
            "model": "gpt-4o-mini",
            "//_comment_env": "Env var for API key / متغير البيئة لمفتاح واجهة البرمجيات",
            "api_key_env": "OPENAI_API_KEY",
            "//_comment_batch": "Number of keys per AI prompt / عدد المفاتيح في كل مطالبة ذكاء اصطناعي",
            "batch_size": 20,
            "//_comment_short": "Max words to skip semantic check / أقصى عدد كلمات لتجاوز الفحص الدلالي",
            "short_label_threshold": 3
        },
        
        "output": {
            "//_comment_dir": "Results directory path / مسار دليل النتائج",
            "results_dir": "Results",
            "//_comment_mode": "Handling previous results (archive/overwrite) / التعامل مع النتائج السابقة (أرشيف/استبدال)",
            "retention_mode": "overwrite",
            "//_comment_prefix": "Archive folder prefix / بادئة مجلد الأرشيف",
            "archive_name_prefix": "audit"
        },
        
        "project_root": ".",
        "glossary_file": WORKSPACE_GLOSSARY,
        "languagetool_dir": "vendor",
        "ar_locale_qc": {
            "enable_exclamation_style": True,
            "enable_long_ui_string": True,
            "enable_similar_phrase_variation": True,
            "enable_suspicious_literal_translation": True,
        },
        "icu_message_audit": {
            "enabled": True,
            "strict_branch_matching": True,
            "enable_selectordinal": True,
        },
    }


def glossary_template_payload() -> dict[str, Any]:
    return {
        "meta": {
            "name": "Project Glossary Example",
            "version": "1.0",
            "status": "example",
            "source_language": "en",
            "target_language": "ar",
            "description": "Small neutral glossary example that shows the expected structure. Replace these entries with your project's approved terminology.",
        },
        "rules": {
            "forbidden_terms": [
                {"forbidden_ar": "ملف تعريفي", "use_instead": "ملف شخصي"},
            ]
        },
        "terms": [
            {
                "term_en": "Profile",
                "approved_ar": "ملف شخصي",
                "forbidden_ar": ["ملف تعريفي"],
                "category": "generic_ui",
                "definition": "A neutral example of a preferred Arabic UI term.",
            },
            {
                "term_en": "Save",
                "approved_ar": "حفظ",
                "forbidden_ar": ["خزن"],
                "category": "generic_ui",
                "definition": "A neutral example for a common action label.",
            },
        ],
    }


def version_payload(channel: str = "stable") -> dict[str, Any]:
    return {
        "workspace_version": CURRENT_CONFIG_VERSION,
        "toolkit_version": toolkit_version(),
        "channel": channel,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def default_repository_url() -> str:
    return str(os.environ.get("L10N_AUDIT_REPOSITORY", "")).strip()


def resolve_archive_url(repo: str, channel: str) -> str:
    repo = repo.strip()
    if not repo:
        raise ValueError("A repository URL is required for --from-github. Pass --repo or set L10N_AUDIT_REPOSITORY.")
    if repo.endswith(".zip") or repo.startswith("file://"):
        return repo
    parsed = urlparse(repo)
    if "github.com" not in parsed.netloc:
        raise ValueError("--repo must be a GitHub repository URL or a direct .zip archive URL.")
    clean = repo.rstrip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]
    ref = "main" if channel == "main" else f"v{toolkit_version()}"
    return f"{clean}/archive/refs/{'heads' if channel == 'main' else 'tags'}/{ref}.zip"


def sync_templates_from_archive(project_root: Path, archive_url: str, channel: str) -> dict[str, Any]:
    target_dir = workspace_template_dir(project_root)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with urlopen(archive_url) as response:
        archive_bytes = response.read()

    extracted_files = 0
    with ZipFile(io.BytesIO(archive_bytes)) as archive:
        for member in archive.infolist():
            parts = Path(member.filename).parts
            if not parts or member.is_dir():
                continue
            relative_parts = parts[1:] if len(parts) > 1 else parts
            if not relative_parts:
                continue
            destination = target_dir.joinpath(*relative_parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted_files += 1

    return {
        "archive_url": archive_url,
        "channel": channel,
        "template_dir": target_dir,
        "extracted_files": extracted_files,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def init_workspace(
    project_root: Path,
    *,
    force: bool = False,
    channel: str = "stable",
    from_github: bool = False,
    repo: str | None = None,
) -> dict[str, Any]:
    workspace = workspace_dir(project_root)
    workspace.mkdir(parents=True, exist_ok=True)
    profile_name, detection = detect_project_profile(project_root)
    if profile_name == "unknown":
        profile_name = "auto"

    config_path = workspace_config_path(project_root)
    if force or not config_path.exists():
        from l10n_audit.models import AuditOptions
        payload = AuditOptions().default_config_json(profile_name)
        config_path.write_text(payload, encoding="utf-8")

    glossary_path = workspace_glossary_path(project_root)
    if force or not glossary_path.exists():
        write_json(glossary_path, glossary_template_payload())

    results_dir = workspace / "Results"
    results_dir.mkdir(parents=True, exist_ok=True)
    sync_info: dict[str, Any] | None = None
    if from_github:
        archive_url = resolve_archive_url(repo or default_repository_url(), channel)
        sync_info = sync_templates_from_archive(project_root, archive_url, channel)
    version = version_payload(channel=channel)
    if sync_info:
        version["github_sync"] = {
            "archive_url": sync_info["archive_url"],
            "template_dir": str(sync_info["template_dir"]),
            "extracted_files": sync_info["extracted_files"],
        }
    write_json(workspace_version_path(project_root), version)

    result = {
        "project_root": project_root,
        "workspace_dir": workspace,
        "config_path": config_path,
        "glossary_path": glossary_path,
        "results_dir": results_dir,
        "profile_name": profile_name,
        "detection": detection,
    }
    if sync_info:
        result["github_sync"] = sync_info
    return result


def update_workspace(
    project_root: Path,
    *,
    channel: str = "stable",
    from_github: bool = False,
    repo: str | None = None,
) -> dict[str, Any]:
    workspace = workspace_dir(project_root)
    if not workspace.exists():
        return init_workspace(project_root, force=False, channel=channel, from_github=from_github, repo=repo)

    config_path = workspace_config_path(project_root)
    if config_path.exists():
        current = read_json(config_path)
    else:
        current = {}
    detected_profile, _detection = detect_project_profile(project_root)
    defaults = default_workspace_config(project_root, detected_profile if detected_profile != "unknown" else str(current.get("project_profile") or "auto"))
    merged = dict(defaults)
    merged.update(current)
    merged["config_version"] = CURRENT_CONFIG_VERSION
    backup_path = config_path.with_suffix(".backup.json")
    if config_path.exists():
        shutil.copy2(config_path, backup_path)
    write_json(config_path, merged)

    glossary_path = workspace_glossary_path(project_root)
    if not glossary_path.exists():
        write_json(glossary_path, glossary_template_payload())

    sync_info: dict[str, Any] | None = None
    if from_github:
        archive_url = resolve_archive_url(repo or default_repository_url(), channel)
        sync_info = sync_templates_from_archive(project_root, archive_url, channel)
    version = version_payload(channel=channel)
    if sync_info:
        version["github_sync"] = {
            "archive_url": sync_info["archive_url"],
            "template_dir": str(sync_info["template_dir"]),
            "extracted_files": sync_info["extracted_files"],
        }
    write_json(workspace_version_path(project_root), version)
    result = {
        "project_root": project_root,
        "workspace_dir": workspace,
        "config_path": config_path,
        "backup_path": backup_path if backup_path.exists() else None,
        "glossary_path": glossary_path,
    }
    if sync_info:
        result["github_sync"] = sync_info
    return result


def workspace_status(project_root: Path) -> dict[str, Any]:
    workspace = workspace_dir(project_root)
    config_path = workspace_config_path(project_root)
    version_path = workspace_version_path(project_root)
    glossary_path = workspace_glossary_path(project_root)
    profile_name, detection = detect_project_profile(project_root)
    return {
        "project_root": project_root,
        "workspace_dir": workspace,
        "workspace_exists": workspace.exists(),
        "config_exists": config_path.exists(),
        "version_exists": version_path.exists(),
        "glossary_exists": glossary_path.exists(),
        "detected_profile": profile_name,
        "detection": detection,
        "config_path": config_path,
        "version_path": version_path,
        "glossary_path": glossary_path,
    }


def _copy_path(src: Path, dst: Path) -> None:
    """Helper to copy a file or a directory structure."""
    if not src.exists():
        return
    if src.is_file():
        shutil.copy2(src, dst)
    elif src.is_dir():
        # dirs_exist_ok=True is used because we ensure workspace is clean/prepapped
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore_dangling_symlinks=True)


def prepare_audit_workspace(runtime: Any, force_clean: bool = True) -> Any:
    """Prepares an isolated workspace for the current audit run.
    
    Copies original locale files into .l10n-audit/workspace/ to prevent
    accidental modification of source data.
    
    Returns the updated runtime object with paths pointing to the workspace.
    """
    project_root = runtime.project_root
    ws_base = workspace_dir(project_root) / WORKSPACE_RUN_DIR
    
    # 1. Clean workspace before run to avoid data accumulation
    if force_clean and ws_base.exists():
        shutil.rmtree(ws_base, ignore_errors=True)
    
    ws_base.mkdir(parents=True, exist_ok=True)
    
    # 2. Copy EN/AR files/directories into workspace
    # 2a. Store originals for fix-application phase later
    if hasattr(runtime, "en_file"):
        runtime.original_en_file = runtime.en_file
    if hasattr(runtime, "ar_file"):
        runtime.original_ar_file = runtime.ar_file

    # 2b. Maintain the original filename/extension in the workspace
    if hasattr(runtime, "en_file") and runtime.en_file.exists():
        target_en = ws_base / runtime.en_file.name
        _copy_path(runtime.en_file, target_en)
        # Update runtime in-memory to point to the isolated copy
        runtime.en_file = target_en
        
    if hasattr(runtime, "ar_file") and runtime.ar_file.exists():
        target_ar = ws_base / runtime.ar_file.name
        _copy_path(runtime.ar_file, target_ar)
        # Update runtime in-memory to point to the isolated copy
        runtime.ar_file = target_ar
        
    return runtime
