from __future__ import annotations

import json
from pathlib import Path

from core.audit_runtime import AuditRuntimeError


def load_json_locale(path: Path) -> dict[str, object]:
    if not path.exists():
        raise AuditRuntimeError(f"Locale source not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuditRuntimeError(f"JSON root must be an object: {path}")
    return {str(key): value for key, value in data.items()}
