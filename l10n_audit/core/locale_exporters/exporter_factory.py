from __future__ import annotations

from pathlib import Path
from typing import Callable

from l10n_audit.core.audit_runtime import AuditRuntimeError
from l10n_audit.core.locale_exporters.json_exporter import export_json_locale
from l10n_audit.core.locale_exporters.laravel_php_exporter import export_laravel_php_locale

LocaleExporter = Callable[[dict[str, object], Path], list[Path]]


EXPORTERS: dict[str, LocaleExporter] = {
    "json": export_json_locale,
    "laravel_php": export_laravel_php_locale,
}


def get_exporter(locale_format: str) -> LocaleExporter:
    exporter = EXPORTERS.get(locale_format)
    if exporter is None:
        raise AuditRuntimeError(f"Unsupported locale export format: {locale_format}")
    return exporter


def export_locale_mapping(mapping: dict[str, object], locale_format: str, output_path: Path) -> list[Path]:
    return get_exporter(locale_format)(mapping, output_path)
