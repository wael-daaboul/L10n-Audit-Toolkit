import shutil
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from l10n_audit.models import AuditOptions

logger = logging.getLogger("l10n_audit.results_manager")

def manage_previous_results(results_dir: Path, options: AuditOptions) -> None:
    """Manage the Results/ directory according to retention policy.
    
    Safety: This function strictly operates within the provided results_dir.
    It will never touch files outside this directory.
    """
    # SKIP cleanup if we are in 'autofix' or 'reports' stage to maintain idempotency
    if options.stage in {"autofix", "reports"}:
        logger.info("Skipping results cleanup for stage: %s", options.stage)
        if not results_dir.exists():
            results_dir.mkdir(parents=True, exist_ok=True)
        return

    if not results_dir.exists():
        results_dir.mkdir(parents=True, exist_ok=True)
        return

    prefix = options.output.archive_name_prefix or "audit"
    mode = options.output.retention_mode or "overwrite"
    archive_regex = re.compile(rf"^{re.escape(prefix)}_v(\d+)$")

    if mode == "overwrite":
        logger.info("Cleaning up previous results in %s (overwrite mode)", results_dir)
        for item in results_dir.iterdir():
            # Safety: Do NOT delete folders that look like archives
            if item.is_dir() and archive_regex.match(item.name):
                continue
            
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                logger.warning("Failed to delete %s during results cleanup: %s", item, e)
                
    elif mode == "archive":
        # 1. Generate timestamped archive name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"{prefix}_{timestamp}"
        archive_path = results_dir / archive_name
        
        # 2. Identify active report items (anything NOT an archive folder)
        # We assume folders matching prefix_* or containing v(\d+) are archives
        items_to_archive = []
        for item in results_dir.iterdir():
            if item.is_dir():
                # Avoid archiving existing archives
                if item.name.startswith(f"{prefix}_"):
                    continue
            
            # Skip the newly planned archive path
            if item.name == archive_name:
                continue
            items_to_archive.append(item)
            
        if items_to_archive:
            logger.info("Archiving previous results to %s", archive_path)
            archive_path.mkdir(parents=True, exist_ok=True)
            for item in items_to_archive:
                try:
                    # Use shutil.move for both files and directories
                    shutil.move(str(item), str(archive_path / item.name))
                except Exception as e:
                    logger.warning("Failed to archive %s: %s", item, e)


def get_staged_dir(project_root: Path) -> Path:
    """Returns the persistent staged directory path."""
    staged = project_root / ".l10n-audit" / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    return staged


def migrate_verified_to_staged(project_root: Path, results: Any) -> None:
    """Copies verified translations to persistent staged storage.
    
    'results' is expected to be an AuditResult object or a dict with 'issues'.
    """
    import json
    staged_dir = get_staged_dir(project_root)
    approved_file = staged_dir / "approved_translations.json"
    
    # Load existing approved translations if they exist
    existing_approved = {}
    if approved_file.exists():
        try:
            existing_approved = json.loads(approved_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load existing approved translations: %s", e)

    # Extract verified issues
    issues = []
    if hasattr(results, "issues"):
        issues = results.issues
    elif isinstance(results, dict):
        issues = results.get("issues", [])

    new_approved_count = 0
    for issue in issues:
        # Check for verified flag in issue or extra
        is_verified = False
        if hasattr(issue, "verified") and getattr(issue, "verified") is True:
            is_verified = True
        elif hasattr(issue, "extra"):
            is_verified = issue.extra.get("verified") is True
        elif isinstance(issue, dict):
            is_verified = issue.get("verified") is True or issue.get("extra", {}).get("verified") is True
        
        if is_verified:
            key = getattr(issue, "key", "") if not isinstance(issue, dict) else issue.get("key", "")
            locale = getattr(issue, "locale", "") if not isinstance(issue, dict) else issue.get("locale", "")
            suggestion = getattr(issue, "suggestion", "") if not isinstance(issue, dict) else issue.get("suggestion", "")
            file_path = getattr(issue, "file", "") if not isinstance(issue, dict) else issue.get("file", "")
            source_text = getattr(issue, "source", "") if not isinstance(issue, dict) else issue.get("source", "")

            if key and locale and suggestion:
                existing_approved[f"{locale}:{key}"] = {
                    "key": key,
                    "locale": locale,
                    "suggestion": suggestion,
                    "source_text": source_text,
                    "file": file_path,
                    "migrated_at": datetime.now().isoformat()
                }
                new_approved_count += 1

    if new_approved_count > 0:
        logger.info("Migrated %d verified translations to %s", new_approved_count, approved_file)
        approved_file.write_text(json.dumps(existing_approved, indent=2, ensure_ascii=False), encoding="utf-8")


def save_to_staged(project_root: Path, item: dict) -> None:
    """Saves a single verified suggestion directly to staged storage."""
    import json
    staged_dir = get_staged_dir(project_root)
    approved_file = staged_dir / "approved_translations.json"
    
    existing_approved = {}
    if approved_file.exists():
        try:
            existing_approved = json.loads(approved_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    key = item.get("key")
    locale = item.get("locale", "ar") # Default to ar if missing
    suggestion = item.get("suggestion")
    
    if key and suggestion:
        existing_approved[f"{locale}:{key}"] = {
            "key": key,
            "locale": locale,
            "suggestion": suggestion,
            "source_text": item.get("source", ""),
            "file": item.get("file", ""),
            "migrated_at": datetime.now().isoformat(),
            "verified": True
        }
        approved_file.write_text(json.dumps(existing_approved, indent=2, ensure_ascii=False), encoding="utf-8")

