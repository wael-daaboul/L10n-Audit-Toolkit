from __future__ import annotations

import json
from pathlib import Path

from l10n_audit.core.audit_runtime import preserve_original_order


def export_json_locale(mapping: dict[str, object], path: Path) -> list[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = preserve_original_order(mapping)
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    return [path]
