import shutil
import re
import logging
from datetime import datetime
from pathlib import Path
from l10n_audit.models import AuditOptions

logger = logging.getLogger("l10n_audit.results_manager")

def manage_previous_results(results_dir: Path, options: AuditOptions) -> None:
    """Manage the Results/ directory according to retention policy.
    
    Safety: This function strictly operates within the provided results_dir.
    It will never touch files outside this directory.
    """
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
