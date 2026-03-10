from __future__ import annotations

import json
from pathlib import Path

from core.audit_runtime import AuditRuntimeError


def _flatten_json_object(
    value: dict[str, object],
    *,
    prefix: str = "",
    target: dict[str, object] | None = None,
) -> dict[str, object]:
    flattened = target if target is not None else {}
    for raw_key, item in value.items():
        key = str(raw_key)
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            _flatten_json_object(item, prefix=full_key, target=flattened)
            continue
        if full_key in flattened:
            raise AuditRuntimeError(f"JSON locale contains a structural collision at '{full_key}': {prefix or key}")
        parent_segments = full_key.split(".")
        for index in range(1, len(parent_segments)):
            parent_key = ".".join(parent_segments[:index])
            if parent_key in flattened:
                raise AuditRuntimeError(
                    f"JSON locale contains a structural collision between '{parent_key}' and '{full_key}'."
                )
        flattened[full_key] = item
    return flattened


def load_json_locale(path: Path) -> dict[str, object]:
    if not path.exists():
        raise AuditRuntimeError(f"Locale source not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuditRuntimeError(f"JSON root must be an object: {path}")
    return _flatten_json_object(data)
