from __future__ import annotations

from pathlib import Path

from l10n_audit.core.audit_runtime import AuditRuntimeError


def _php_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _insert_nested(target: dict[str, object], parts: list[str], value: object) -> None:
    import logging
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        elif not isinstance(child, dict):
            # Collision!
            full_key = ".".join(parts)
            logging.warning(f"Structural collision at key '{full_key}': part '{part}' is already a scalar. Keeping key flat.")
            target[full_key] = value
            return
        current = child
    
    last_part = parts[-1]
    existing = current.get(last_part)
    if isinstance(existing, dict):
        full_key = ".".join(parts)
        logging.warning(f"Structural collision at key '{full_key}': final part is already a dict. Keeping key flat.")
        target[full_key] = value
    else:
        current[last_part] = value


def _serialize_php(value: object, indent: int = 0) -> str:
    indent_text = "    " * indent
    next_indent = "    " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "[]"
        lines = ["["]
        for key in value:
            rendered = _serialize_php(value[key], indent + 1)
            lines.append(f"{next_indent}'{_php_escape(str(key))}' => {rendered},")
        lines.append(f"{indent_text}]")
        return "\n".join(lines)
    return f"'{_php_escape(str(value))}'"


def _group_mapping(mapping: dict[str, object]) -> dict[str, dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    for full_key, value in mapping.items():
        parts = str(full_key).split(".")
        if len(parts) == 1:
            group = "_ungrouped"
            nested_parts = [parts[0]]
        else:
            group = parts[0]
            nested_parts = parts[1:]
        groups.setdefault(group, {})
        _insert_nested(groups[group], nested_parts, value)
    return groups


def export_laravel_php_locale(mapping: dict[str, object], directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for group, payload in _group_mapping(mapping).items():
        path = directory / f"{group}.php"
        content = "<?php\n\nreturn " + _serialize_php(payload) + ";\n"
        path.write_text(content, encoding="utf-8")
        outputs.append(path)
    return outputs
