"""
Input validators for the l10n_audit Python API.

All validators raise the appropriate :mod:`l10n_audit.exceptions` subclass
on failure so callers can handle errors at the right abstraction level.
"""
from __future__ import annotations

from pathlib import Path

from l10n_audit.exceptions import AIConfigError, InvalidProjectError, StageError
from l10n_audit.models import VALID_STAGES


def validate_project_path(project_path: str | Path) -> Path:
    """Ensure *project_path* exists and is a directory.

    Returns
    -------
    Path
        The resolved, absolute project path.

    Raises
    ------
    InvalidProjectError
        If the path does not exist or is not a directory.
    """
    path = Path(project_path).resolve()
    if not path.exists():
        raise InvalidProjectError(
            f"Project path does not exist: {path}"
        )
    if not path.is_dir():
        raise InvalidProjectError(
            f"Project path must be a directory, got file: {path}"
        )
    return path


def validate_stage(stage: str) -> str:
    """Ensure *stage* is a supported audit stage name.

    Returns
    -------
    str
        The validated stage string (unchanged).

    Raises
    ------
    StageError
        If *stage* is not in the supported set.
    """
    if stage not in VALID_STAGES:
        raise StageError(
            f"Unknown audit stage: {stage!r}. "
            f"Valid stages: {', '.join(sorted(VALID_STAGES))}"
        )
    return stage


def validate_ai_config(
    *,
    ai_enabled: bool,
    ai_api_key: str | None,
    ai_model: str | None,
    ai_api_base: str | None,
) -> dict[str, str]:
    """Validate AI configuration and return a sanitised config dict.

    When *ai_enabled* is ``False`` this is a no-op (returns ``{}``).

    Returns
    -------
    dict
        ``{"api_key": ..., "api_base": ..., "model": ...}`` when AI is enabled.

    Raises
    ------
    AIConfigError
        If AI is enabled but no API key is provided.
    """
    if not ai_enabled:
        return {}

    if not ai_api_key:
        raise AIConfigError(
            "AI Review is enabled but no API key was provided. "
            "Pass ai_api_key or set the OPENAI_API_KEY environment variable."
        )

    return {
        "api_key": ai_api_key,
        "api_base": (ai_api_base or "https://api.openai.com/v1").rstrip("/"),
        "model": ai_model or "gpt-4o-mini",
    }


def validate_translation_files(runtime) -> None:  # type: ignore[no-untyped-def]
    """Check that required locale files are accessible on disk.

    Parameters
    ----------
    runtime:
        An :class:`~core.audit_runtime.AuditPaths` instance.

    Raises
    ------
    InvalidProjectError
        If source or target locale files / directories are missing.
    """
    missing: list[str] = []

    if runtime.locale_format == "laravel_php":
        for locale, path in runtime.locale_paths.items():
            if not path.exists():
                missing.append(f"{locale} → {path}")
    else:
        if not runtime.en_file.exists():
            missing.append(f"source locale file → {runtime.en_file}")
        if not runtime.ar_file.exists():
            missing.append(f"target locale file → {runtime.ar_file}")

    if missing:
        raise InvalidProjectError(
            "Required translation files are missing:\n"
            + "\n".join(f"  • {m}" for m in missing)
        )
