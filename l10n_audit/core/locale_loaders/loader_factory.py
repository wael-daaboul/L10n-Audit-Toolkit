from __future__ import annotations

from pathlib import Path
from typing import Callable

from l10n_audit.core.audit_runtime import AuditRuntimeError
from l10n_audit.core.locale_loaders.json_loader import load_json_locale
from l10n_audit.core.locale_loaders.laravel_php_loader import load_laravel_php_locale

LocaleLoader = Callable[[Path], dict[str, object]]


LOADERS: dict[str, LocaleLoader] = {
    "json": load_json_locale,
    "laravel_php": load_laravel_php_locale,
}


def get_loader(locale_format: str) -> LocaleLoader:
    loader = LOADERS.get(locale_format)
    if loader is None:
        raise AuditRuntimeError(f"Unsupported locale format: {locale_format}")
    return loader


def load_locale_mapping(
    path: Path,
    locale_format: str,
    source_locale: str | None = None,
    target_locales: tuple[str, ...] | None = None,
    locale: str | None = None,
) -> dict[str, object]:
    del source_locale, target_locales, locale
    return get_loader(locale_format)(path)
