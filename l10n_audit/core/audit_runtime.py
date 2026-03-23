#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.resources
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZIP_DEFLATED, ZipFile

from l10n_audit.core.profile_detection import AMBIGUITY_MARGIN, LOW_CONFIDENCE_THRESHOLD, autodetect_profile

class AuditRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuditPaths:
    tools_dir: Path
    config_dir: Path
    docs_dir: Path
    vendor_dir: Path
    project_root: Path
    locales_dir: Path
    en_file: Path
    ar_file: Path
    code_dir: Path
    code_dirs: tuple[Path, ...]
    glossary_file: Path
    results_dir: Path
    languagetool_dir: Path
    languagetool_configured_dir: Path | None
    project_profile: str
    locale_format: str
    locale_root: Path
    source_locale: str
    target_locales: tuple[str, ...]
    locale_paths: dict[str, Path]
    usage_patterns: tuple[str, ...]
    usage_wrappers: tuple[str, ...]
    usage_accessors: tuple[str, ...]
    usage_config_fields: tuple[str, ...]
    allowed_extensions: tuple[str, ...]
    profile_notes: str
    profile_selection_mode: str
    profile_score: int
    profile_reasons: tuple[str, ...]
    role_identifiers: tuple[str, ...]
    entity_whitelist: dict[str, tuple[str, ...]]
    latin_whitelist: tuple[str, ...]
    ai_review: dict[str, Any]
    output: dict[str, Any]


def _resolve_config_path(base_dir: Path, raw_value: str | None, fallback: Path) -> Path:
    if not raw_value:
        return fallback.resolve()
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _resolve_many_paths(base_dir: Path, raw_values: Sequence[str] | None, fallback: Sequence[Path]) -> tuple[Path, ...]:
    if not raw_values:
        return tuple(path.resolve() for path in fallback)
    resolved: list[Path] = []
    for raw_value in raw_values:
        candidate = Path(raw_value)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        resolved.append(candidate.resolve())
    return tuple(resolved)


def _discover_glossary_path(docs_dir: Path) -> Path:
    terminology_dir = docs_dir / "terminology"
    preferred = terminology_dir / "glossary.json"
    if preferred.exists():
        return preferred.resolve()
    if terminology_dir.exists():
        candidates = sorted(path for path in terminology_dir.glob("*.json") if path.is_file())
        if candidates:
            return candidates[0].resolve()
    return preferred.resolve()


def _load_json_file(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


LEGACY_FLUTTER_DEFAULTS: dict[str, object] = {
    "locale_format": "json",
    "locales_dir": "assets/language",
    "en_file": "assets/language/en.json",
    "ar_file": "assets/language/ar.json",
    "code_dir": "lib",
    "code_dirs": ["lib"],
    "locale_paths": {
        "en": "assets/language/en.json",
        "ar": "assets/language/ar.json",
    },
}


def _load_project_profiles(config_dir: Path) -> dict[str, dict[str, object]]:
    profiles_path = config_dir / "project_profiles.json"
    payload = _load_json_file(profiles_path)
    if not payload:
        resource_text = importlib.resources.files("l10n_audit.core.resources").joinpath("project_profiles.json").read_text(encoding="utf-8")
        payload = json.loads(resource_text)
    profiles = payload.get("profiles", {}) if isinstance(payload, dict) else {}
    return {str(name): value for name, value in profiles.items() if isinstance(value, dict)}


def _normalize_for_compare(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _normalize_for_compare(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_for_compare(item) for item in value]
    return value


def _config_for_selected_profile(config: dict[str, object], selected_profile: str, selection_mode: str) -> dict[str, object]:
    if selection_mode != "auto" or selected_profile == "flutter_getx_json":
        return dict(config)
    adjusted = dict(config)
    for key, default in LEGACY_FLUTTER_DEFAULTS.items():
        if _normalize_for_compare(adjusted.get(key)) == _normalize_for_compare(default):
            adjusted.pop(key, None)
    return adjusted


def detect_tools_dir(script_path: str | Path) -> Path:
    current = Path(script_path).resolve()
    # Priority: The directory containing the script (if it's a project script)
    if current.is_file():
        parent = current.parent
        if (parent / "config.json").exists() or (parent / "config" / "config.json").exists():
            return parent
            
    search_roots = [current] + list(current.parents)
    for candidate in search_roots:
        if (candidate / "config" / "config.json").exists():
            return candidate
        if (candidate / "Results").is_dir() and (candidate / "docs").is_dir():
            return candidate
    if current.is_dir():
        return current
    return current.parent


def _profile_markers(profile: dict[str, object]) -> list[list[str]]:
    raw = profile.get("project_markers", [])
    markers: list[list[str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, list) and all(isinstance(part, str) for part in item):
                markers.append([str(part) for part in item])
    return markers


def _discover_project_root(tools_dir: Path, configured_root: str | None, profile: dict[str, object]) -> Path:
    candidates: list[Path] = []
    if configured_root:
        candidates.append(_resolve_config_path(tools_dir, configured_root, tools_dir.parent))
    candidates.extend(parent.resolve() for parent in tools_dir.parents)

    markers = _profile_markers(profile)
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if configured_root and candidate.is_dir():
            return candidate
        for marker_group in markers:
            if all((candidate / marker).exists() for marker in marker_group):
                return candidate
    raise AuditRuntimeError(
        "Unable to detect project root. Configure 'project_root' explicitly or use a "
        "profile whose marker paths exist in the target project."
    )


def _merge_profile(config: dict[str, object], profiles: dict[str, dict[str, object]], profile_name: str) -> tuple[str, dict[str, object]]:
    profile = dict(profiles.get(profile_name, {}))
    overrides = config.get("profile_overrides", {})
    if isinstance(overrides, dict):
        profile.update(overrides)
    return profile_name, profile


def _resolve_locale_paths(
    project_root: Path,
    config: dict[str, object],
    profile: dict[str, object],
    locale_format: str,
    source_locale: str,
    target_locales: tuple[str, ...],
) -> tuple[Path, dict[str, Path], Path]:
    locale_root_value = str(config.get("locale_root") or profile.get("locale_root") or "")
    locale_root = _resolve_config_path(project_root, locale_root_value, project_root / "resources" / "lang") if locale_root_value else None
    explicit = config.get("locale_paths", {})
    locale_paths: dict[str, Path] = {}
    if isinstance(explicit, dict):
        for locale, raw_path in explicit.items():
            if isinstance(raw_path, str):
                locale_paths[str(locale)] = _resolve_config_path(project_root, raw_path, project_root / raw_path)

    locale_templates = profile.get("locale_path_templates", {})
    if isinstance(locale_templates, dict):
        for locale in (source_locale, *target_locales):
            if locale in locale_paths:
                continue
            candidates = locale_templates.get(locale) or locale_templates.get("*") or []
            if isinstance(candidates, str):
                candidates = [candidates]
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                rendered = candidate.replace("{locale}", locale)
                resolved = _resolve_config_path(project_root, rendered, project_root / rendered)
                if resolved.exists():
                    locale_paths[locale] = resolved
                    break
                if locale not in locale_paths:
                    locale_paths[locale] = resolved

    if locale_format == "laravel_php" and locale_root:
        for locale in (source_locale, *target_locales):
            locale_paths.setdefault(locale, (locale_root / locale).resolve())

    en_file = locale_paths.get(source_locale)
    ar_file = locale_paths.get(target_locales[0]) if target_locales else None
    if not en_file:
        en_file = _resolve_config_path(project_root, str(config.get("en_file") or config.get("source_locale_file") or ""), project_root / "assets" / "language" / "en.json")
        locale_paths[source_locale] = en_file
    if not ar_file:
        ar_file = _resolve_config_path(project_root, str(config.get("ar_file") or config.get("target_locale_file") or ""), project_root / "assets" / "language" / "ar.json")
        if target_locales:
            locale_paths[target_locales[0]] = ar_file

    locales_dir = _resolve_config_path(project_root, str(config.get("locales_dir") or ""), locale_root or en_file.parent)
    return en_file, locale_paths, locales_dir


def _resolve_code_dirs(project_root: Path, config: dict[str, object], profile: dict[str, object]) -> tuple[Path, tuple[Path, ...]]:
    explicit_code_dirs = config.get("code_dirs")
    if isinstance(explicit_code_dirs, list):
        code_dirs = _resolve_many_paths(project_root, [str(item) for item in explicit_code_dirs], [])
    else:
        raw_code_dir = config.get("code_dir")
        if isinstance(raw_code_dir, str) and raw_code_dir:
            code_dirs = (_resolve_config_path(project_root, raw_code_dir, project_root / raw_code_dir),)
        else:
            candidates = profile.get("code_dir_candidates", [])
            if not isinstance(candidates, list):
                candidates = []
            resolved = _resolve_many_paths(project_root, [str(item) for item in candidates if isinstance(item, str)], [])
            existing = tuple(path for path in resolved if path.exists())
            code_dirs = existing or resolved
    if not code_dirs:
        code_dirs = (project_root / "lib",)
    return code_dirs[0], code_dirs

def _get_nested(config: dict[str, Any], path: str, default: Any = None) -> Any:
    """Read a nested config value (e.g. 'output.results_dir') with flat fallback."""
    parts = path.split(".")
    curr = config
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            # Fallback to the leaf name if it exists at the root (backward compat)
            return config.get(parts[-1], default)
    return curr


def load_runtime(script_path: str | Path, validate: bool = True) -> AuditPaths:
    tools_dir = detect_tools_dir(script_path)
    docs_dir = tools_dir / "docs"
    vendor_dir = tools_dir / "vendor"
    default_config_dir = tools_dir / "config"
    override_config = os.environ.get("L10N_AUDIT_CONFIG")

    # 1. Locate Config File
    config_path = (tools_dir / "config.json").resolve()
    if not config_path.exists():
        # Fallback to config/ subfolder (used by some tools/templates)
        config_path = (tools_dir / "config" / "config.json").resolve()
    
    if override_config:
        config_path = Path(override_config).resolve()

    runtime_config_dir = config_path.parent
    config_root_base = runtime_config_dir if override_config else tools_dir
    path_base_dir = tools_dir # Paths usually relative to .l10n-audit root
    
    config: dict[str, Any] = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    
    internal_config_dir = Path(__file__).resolve().parent.parent / "config"
    profiles = _load_project_profiles(internal_config_dir)
    
    # Preference: project_detection.force_profile -> project_profile
    configured_profile = str(_get_nested(config, "project_detection.force_profile") or config.get("project_profile") or "auto").strip() or "auto"
    configured_root = str(config.get("project_root") or "")

    if configured_profile != "auto":
        if configured_profile not in profiles:
            raise AuditRuntimeError(f"Unknown project_profile '{configured_profile}'.")
        effective_config = dict(config)
        project_profile, profile = _merge_profile(effective_config, profiles, configured_profile)
        project_root = _discover_project_root(config_root_base, configured_root, profile)
        profile_selection_mode = "manual"
        profile_score = 0
        profile_reasons = (f"manual config override: {configured_profile}",)
        ranked_candidates: tuple[object, ...] = ()
    else:
        best_candidate, ranked_candidates = autodetect_profile(config_root_base, configured_root, profiles)
        
        # Check if project_detection.auto_detect is False
        if _get_nested(config, "project_detection.auto_detect", True) is False and validate:
             raise AuditRuntimeError("Manual project detection required: 'auto_detect' is disabled and no 'force_profile' set.")

        second_candidate = ranked_candidates[1] if len(ranked_candidates) > 1 else None
        if best_candidate.score < LOW_CONFIDENCE_THRESHOLD and validate:
            details = "; ".join(
                f"{candidate.profile_name}={candidate.score} ({', '.join(candidate.reasons[:3]) or 'no signals'})"
                for candidate in ranked_candidates[:3]
            )
            raise AuditRuntimeError(
                "Unable to detect project profile with enough confidence. "
                "Set 'project_profile' manually in config/config.json. "
                f"Candidates: {details}"
            )
        if second_candidate and best_candidate.score - second_candidate.score < AMBIGUITY_MARGIN and validate:
            details = "; ".join(
                f"{candidate.profile_name}={candidate.score} ({', '.join(candidate.reasons[:3]) or 'no signals'})"
                for candidate in ranked_candidates[:3]
            )
            raise AuditRuntimeError(
                "Project profile detection is ambiguous. Set 'project_profile' manually in config/config.json. "
                f"Candidates: {details}"
            )
        effective_config = _config_for_selected_profile(config, best_candidate.profile_name, "auto")
        project_profile, profile = _merge_profile(effective_config, profiles, best_candidate.profile_name)
        project_root = best_candidate.project_root
        profile_selection_mode = "auto"
        profile_score = best_candidate.score
        profile_reasons = best_candidate.reasons

    source_locale = str(_get_nested(effective_config, "source_locale") or profile.get("source_locale") or "en")
    raw_targets = _get_nested(effective_config, "target_locales") or profile.get("target_locales") or ["ar"]
    if isinstance(raw_targets, list):
        target_locales = tuple(str(item) for item in raw_targets)
    else:
        target_locales = ("ar",)
    
    locale_format = str(profile.get("locale_format") or _get_nested(effective_config, "locale_format") or "json")
    en_file, locale_paths, locales_dir = _resolve_locale_paths(project_root, effective_config, profile, locale_format, source_locale, target_locales)
    ar_file = locale_paths.get(target_locales[0], _resolve_config_path(project_root, str(_get_nested(effective_config, "ar_file") or ""), project_root / "assets" / "language" / "ar.json"))
    
    code_dir, code_dirs = _resolve_code_dirs(project_root, effective_config, profile)
    
    glossary_file = _resolve_config_path(
        path_base_dir,
        str(_get_nested(effective_config, "glossary_file") or ""),
        _discover_glossary_path(docs_dir),
    )
    
    results_dir = _resolve_config_path(
        path_base_dir,
        str(_get_nested(effective_config, "output.results_dir") or _get_nested(effective_config, "results_dir") or ""),
        tools_dir / "Results",
    )
    
    raw_languagetool_dir = str(_get_nested(effective_config, "languagetool_dir") or "").strip()
    languagetool_configured_dir = (
        _resolve_config_path(path_base_dir, raw_languagetool_dir, vendor_dir)
        if raw_languagetool_dir
        else None
    )
    languagetool_dir = (languagetool_configured_dir or vendor_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)

    runtime = AuditPaths(
        tools_dir=tools_dir,
        config_dir=runtime_config_dir,
        docs_dir=docs_dir,
        vendor_dir=vendor_dir,
        project_root=project_root,
        locales_dir=locales_dir,
        en_file=en_file,
        ar_file=ar_file,
        code_dir=code_dir,
        code_dirs=code_dirs,
        glossary_file=glossary_file,
        results_dir=results_dir,
        languagetool_dir=languagetool_dir,
        languagetool_configured_dir=languagetool_configured_dir,
        project_profile=project_profile,
        locale_format=locale_format,
        locale_root=locales_dir,
        source_locale=source_locale,
        target_locales=target_locales,
        locale_paths=locale_paths,
        usage_patterns=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.usage_patterns", profile.get("usage_patterns") or []))),
        usage_wrappers=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.usage_wrappers", profile.get("usage_wrappers") or ["t", "translate", "i18n", "localize"]))),
        usage_accessors=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.usage_accessors", profile.get("usage_accessors") or ["LocaleKeys", "AppStrings", "TranslationKeys"]))),
        usage_config_fields=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.usage_config_fields", profile.get("usage_config_fields") or ["titleKey", "labelKey", "textKey", "subtitleKey", "translation_key", "messageKey"]))),
        allowed_extensions=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.allowed_extensions", profile.get("allowed_extensions") or []))),
        profile_notes=str(profile.get("notes") or ""),
        profile_selection_mode=profile_selection_mode,
        profile_score=profile_score,
        profile_reasons=profile_reasons,
        role_identifiers=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.role_identifiers") or _get_nested(effective_config, "audit_rules.domain_roles") or [])),
        entity_whitelist={
            lang: tuple(str(item) for item in terms)
            for lang, terms in (
                _get_nested(effective_config, "audit_rules.entity_whitelist") or {"en": [], "ar": []}
            ).items()
            if isinstance(terms, (list, tuple))
        },
        latin_whitelist=tuple(str(item) for item in (_get_nested(effective_config, "audit_rules.latin_whitelist") or [])),
        ai_review={
            "enabled": _get_nested(effective_config, "ai_review.enabled", False),
            "provider": _get_nested(effective_config, "ai_review.provider", "litellm"),
            "model": _get_nested(effective_config, "ai_review.model", "gpt-4o-mini"),
            "api_key_env": _get_nested(effective_config, "ai_review.api_key_env", "OPENAI_API_KEY"),
            "batch_size": _get_nested(effective_config, "ai_review.batch_size", 20),
            "short_label_threshold": _get_nested(effective_config, "ai_review.short_label_threshold", 3),
        },
        output={
            "retention_mode": _get_nested(effective_config, "output.retention_mode", "overwrite"),
            "archive_name_prefix": _get_nested(effective_config, "output.archive_name_prefix", "audit"),
            "apply_safe_fixes": _get_nested(effective_config, "audit_rules.apply_safe_fixes", False),
        }
    )
    if validate:
        validate_runtime(runtime)
    return runtime


def validate_runtime(runtime: AuditPaths) -> None:
    missing: list[str] = []

    if not runtime.locales_dir.exists():
        missing.append(f"locales_dir={runtime.locales_dir}")

    if runtime.locale_format == "laravel_php":
        locale_requirements = {
            runtime.source_locale: runtime.en_file,
            **{locale: runtime.locale_paths.get(locale, runtime.ar_file) for locale in runtime.target_locales},
        }
        for locale, path in locale_requirements.items():
            if not path.exists():
                missing.append(f"{locale}_locale={path}")
                continue
            if path.is_dir():
                if not any(child.suffix == ".php" for child in path.iterdir() if child.is_file()):
                    missing.append(f"{locale}_locale_php_files={path}")
            elif path.suffix != ".php":
                missing.append(f"{locale}_locale_php={path}")
    else:
        required_paths = {
            "en_file": runtime.en_file,
            "ar_file": runtime.ar_file,
        }
        for name, path in required_paths.items():
            if not path.exists():
                missing.append(f"{name}={path}")

    if not runtime.code_dir.exists():
        missing.append(f"code_dir={runtime.code_dir}")

    if missing:
        raise AuditRuntimeError("Missing required paths: " + ", ".join(missing))


def load_json_dict(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuditRuntimeError(f"JSON root must be an object: {path}")
    return {str(key): value for key, value in data.items()}


def load_locale_mapping(path: Path, runtime: AuditPaths, locale: str | None = None) -> dict[str, object]:
    from l10n_audit.core.locale_loaders import load_locale_mapping as _load_locale_mapping

    return _load_locale_mapping(
        path=path,
        locale_format=runtime.locale_format,
        source_locale=runtime.source_locale,
        target_locales=runtime.target_locales,
        locale=locale,
    )


def project_relative(path: Path, runtime: AuditPaths) -> str:
    try:
        return path.resolve().relative_to(runtime.project_root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(runtime.tools_dir).as_posix()
        except ValueError:
            return path.resolve().as_posix()


def safe_csv_value(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def write_csv(rows: Sequence[dict[str, object]], fieldnames: Sequence[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: safe_csv_value(row.get(field, "")) for field in fieldnames})


def write_json(payload: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def results_bucket(runtime: AuditPaths, *parts: str) -> Path:
    bucket = runtime.results_dir.joinpath(*parts)
    bucket.mkdir(parents=True, exist_ok=True)
    return bucket


def publish_result(path: Path, runtime: AuditPaths, *bucket_parts: str) -> Path:
    if not path.exists():
        raise AuditRuntimeError(f"Cannot publish missing result: {path}")
    target = results_bucket(runtime, *bucket_parts) / path.name
    if path.resolve() != target.resolve():
        shutil.copy2(path, target)
    return target


def _excel_column_name(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _excel_column_index(label: str) -> int:
    index = 0
    for char in label:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - 64)
    return max(index - 1, 0)


def _xlsx_shared_strings(rows: Sequence[Sequence[str]]) -> tuple[list[str], dict[str, int]]:
    values: list[str] = []
    indices: dict[str, int] = {}
    for row in rows:
        for value in row:
            if value not in indices:
                indices[value] = len(values)
                values.append(value)
    return values, indices


def write_simple_xlsx(
    rows: Sequence[dict[str, object]],
    fieldnames: Sequence[str],
    path: Path,
    sheet_name: str = "Audit",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table: list[list[str]] = [list(fieldnames)]
    for row in rows:
        table.append([safe_csv_value(row.get(field, "")) for field in fieldnames])

    shared_strings, string_index = _xlsx_shared_strings(table)
    last_column = _excel_column_name(len(fieldnames))
    dimension = f"A1:{last_column}{len(table)}"

    sheet_rows: list[str] = []
    for row_number, row in enumerate(table, start=1):
        cells: list[str] = []
        for column_number, value in enumerate(row, start=1):
            cell_ref = f"{_excel_column_name(column_number)}{row_number}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{string_index[value]}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_xml = "".join(
        f"<si><t>{xml_escape(value)}</t></si>" for value in shared_strings
    )
    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<dimension ref=\"{dimension}\"/>"
        "<sheetViews><sheetView workbookViewId=\"0\"/></sheetViews>"
        "<sheetFormatPr defaultRowHeight=\"15\"/>"
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        f"{shared_xml}</sst>"
    )

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_strings_xml)
        archive.writestr("xl/styles.xml", styles_xml)


def read_simple_xlsx(path: Path, required_columns: Sequence[str] | None = None) -> list[dict[str, str]]:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("main:si", namespace):
                shared_strings.append("".join(text or "" for text in item.itertext()))

        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row in worksheet.findall(".//main:sheetData/main:row", namespace):
            values_by_index: dict[int, str] = {}
            for cell in row.findall("main:c", namespace):
                cell_ref = cell.attrib.get("r", "")
                column_label = "".join(ch for ch in cell_ref if ch.isalpha())
                column_index = _excel_column_index(column_label) if column_label else len(values_by_index)
                cell_type = cell.attrib.get("t", "")
                value_node = cell.find("main:v", namespace)
                raw_value = value_node.text if value_node is not None and value_node.text is not None else ""
                if cell_type == "s" and raw_value.isdigit():
                    index = int(raw_value)
                    values_by_index[column_index] = shared_strings[index] if index < len(shared_strings) else ""
                else:
                    values_by_index[column_index] = raw_value
            if values_by_index:
                max_index = max(values_by_index)
                rows.append([values_by_index.get(index, "") for index in range(max_index + 1)])

    if not rows:
        return []
    header = rows[0]
    if required_columns:
        missing = [column for column in required_columns if column not in header]
        if missing:
            raise AuditRuntimeError(f"Malformed XLSX sheet '{path}': missing required columns: {', '.join(missing)}")
    table: list[dict[str, str]] = []
    for row in rows[1:]:
        padded = row + [""] * max(0, len(header) - len(row))
        table.append({str(field): str(value) for field, value in zip(header, padded)})
    return table


def ensure_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def iter_rows(mapping: dict[str, object]) -> Iterable[tuple[str, str]]:
    for key, value in mapping.items():
        if isinstance(value, str):
            yield key, value


HTML_TAG_RE = re.compile(r"<[^>]+>")
ICU_BLOCK_RE = re.compile(r"\{[^{}]+,\s*(plural|select|selectordinal)\s*,", re.IGNORECASE)
URL_RE = re.compile(r"(https?://\S+|www\.\S+)", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PATH_RE = re.compile(r"(?:\b[a-zA-Z]:\\[^\s]+|(?:^|[\s(])(?:/|~/)[^\s]+)")
FLAG_RE = re.compile(r"(^|[\s(])--[A-Za-z0-9][A-Za-z0-9-]*")
CODE_SPAN_RE = re.compile(r"`[^`]+`")
CLI_COMMAND_RE = re.compile(r"(^|\s)(npm|yarn|pnpm|npx|cd|ls|cat|pip|python|node|git|cargo|composer)\b")
CAMEL_OR_BRAND_RE = re.compile(r"\b(?:[a-z]+[A-Z][A-Za-z0-9]*|iPhone|iPad|macOS|GitHub)\b")
PLACEHOLDER_LIKE_RE = re.compile(
    r"(%(?:\d+\$)?[@sdfox]|\$\{[A-Za-z0-9_]+\}|\{\{?[A-Za-z0-9_]+\}?\}|\$\d+|:\w+|#)"
)


def compute_text_hash(value: object) -> str:
    text = value if isinstance(value, str) else str(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_plan_id(*parts: object) -> str:
    joined = "\x1f".join(str(part) for part in parts)
    return compute_text_hash(joined)[:16]


def has_html_or_xml(text: str) -> bool:
    return bool(HTML_TAG_RE.search(text))


def has_icu_syntax(text: str) -> bool:
    return bool(ICU_BLOCK_RE.search(text))


def is_likely_technical_text(text: str) -> bool:
    return any(
        (
            URL_RE.search(text),
            EMAIL_RE.search(text),
            PATH_RE.search(text),
            FLAG_RE.search(text),
            CODE_SPAN_RE.search(text),
            CLI_COMMAND_RE.search(text),
            CAMEL_OR_BRAND_RE.search(text),
            "://" in text,
            "\\" in text,
        )
    )


def is_risky_for_whitespace_normalization(text: str) -> bool:
    return any(
        (
            "\n" in text,
            "\r" in text,
            "\t" in text,
            has_html_or_xml(text),
            has_icu_syntax(text),
            bool(parse_placeholders(text)),
            is_likely_technical_text(text),
        )
    )


def preserve_original_order(mapping: dict[str, object]) -> dict[str, object]:
    return {key: mapping[key] for key in mapping}


def extract_placeholders(text: str) -> set[str]:
    return {str(item["raw"]) for item in parse_placeholders(text)}


def _looks_like_colon_placeholder(text: str, start: int, end: int) -> bool:
    before = text[:start]
    preceding_word = re.search(r"([A-Za-z][A-Za-z0-9+.-]*)$", before)
    if preceding_word:
        protocol = preceding_word.group(1).lower()
        if protocol in {"http", "https", "mailto", "tel", "ftp", "file"}:
            return False
    prev_char = before[-1] if before else ""
    if prev_char and (prev_char.isalnum() or prev_char in {"/", "\\", "-", "`"}):
        return False
    next_char = text[end:end + 1]
    if next_char and next_char in {"/", "\\", "@"}:
        return False
    return True


def _add_placeholder_match(
    items: list[dict[str, object]],
    occupied: list[tuple[int, int]],
    *,
    style: str,
    raw: str,
    canonical: str,
    name: str,
    position: str,
    start: int,
    end: int,
) -> None:
    if any(not (end <= left or start >= right) for left, right in occupied):
        return
    occupied.append((start, end))
    items.append(
        {
            "raw": raw,
            "style": style,
            "canonical": canonical,
            "name": name,
            "position": position,
            "start": start,
            "end": end,
        }
    )


def parse_placeholders(text: str) -> list[dict[str, object]]:
    token_specs = [
        ("dollar_brace", re.compile(r"\$\{(?P<name>[A-Za-z0-9_]+)\}")),
        ("mustache", re.compile(r"\{\{(?P<name>[A-Za-z0-9_]+)\}\}")),
        ("brace", re.compile(r"\{(?P<name>[A-Za-z0-9_]+)\}")),
        ("printf", re.compile(r"%(?:(?P<position>\d+)\$)?(?P<spec>@|[sdfox])")),
        ("dollar_index", re.compile(r"\$(?P<position>\d+)")),
        ("colon", re.compile(r":(?P<name>[A-Za-z_][A-Za-z0-9_]*)")),
    ]

    items: list[dict[str, object]] = []
    occupied: list[tuple[int, int]] = []
    unnamed_index = 0

    for style, pattern in token_specs:
        for match in pattern.finditer(text):
            start, end = match.span()
            name = match.groupdict().get("name") or ""
            spec = match.groupdict().get("spec") or ""
            position = match.groupdict().get("position") or ""
            if style == "printf":
                if not position:
                    position = str(unnamed_index)
                    unnamed_index += 1
                canonical = f"%{spec}:{position}"
                placeholder_name = spec
            elif style == "dollar_index":
                canonical = f"${position}"
                placeholder_name = position
            elif style == "colon":
                if not _looks_like_colon_placeholder(text, start, end):
                    continue
                canonical = f":{name}"
                placeholder_name = name
            else:
                canonical = name
                placeholder_name = name
            _add_placeholder_match(
                items,
                occupied,
                style=style,
                raw=match.group(0),
                canonical=canonical,
                name=placeholder_name,
                position=position,
                start=start,
                end=end,
            )

    if has_icu_syntax(text):
        for match in re.finditer(r"#", text):
            _add_placeholder_match(
                items,
                occupied,
                style="icu_pound",
                raw="#",
                canonical="#",
                name="#",
                position="",
                start=match.start(),
                end=match.end(),
            )

    items.sort(key=lambda item: int(item["start"]))
    return items


def mask_placeholders(text: str) -> tuple[str, list[str]]:
    """Replace all detected placeholders with unique positional tokens.

    This preserves variables like {name}, :id, or %s from being corrupted
    by regex-based locale cleanup rules (e.g. Arabic spacing rules).

    Returns
    -------
    tuple[str, list[str]]
        (masked_text, list_of_original_placeholders)
    """
    placeholders = parse_placeholders(text)
    if not placeholders:
        return text, []

    # Get original placeholders in sequential order (ascending start)
    sequential = sorted(placeholders, key=lambda x: int(x["start"]))
    original_placeholders = [str(p["raw"]) for p in sequential]

    # Replace from front to back? No, back to front is safer for index stability
    # if we use slices, but we need to know WHICH placeholder we are replacing.
    # Map each placeholder to its original sequential index.
    indexed_placeholders = []
    for i, p in enumerate(sequential):
        indexed_placeholders.append((i, p))

    # Sort by start descending
    indexed_placeholders.sort(key=lambda x: int(x[1]["start"]), reverse=True)

    masked = text
    for i, p in indexed_placeholders:
        start, end = int(p["start"]), int(p["end"])
        token = f"[[PH_{i}]]"
        masked = masked[:start] + token + masked[end:]

    return masked, original_placeholders


def unmask_placeholders(masked_text: str, placeholders: list[str]) -> str:
    """Restore original placeholders into a previously masked string.

    Parameters
    ----------
    masked_text:
        String containing [[PH_0]], [[PH_1]] tokens.
    placeholders:
        Original strings to restore in index order.
    """
    result = masked_text
    # Replace tokens in reverse order if they contain each other?
    # Not likely with [[PH_%d]], but let's be safe.
    # Actually, we should replace from largest index to smallest to avoid
    # replacing [[PH_10]] with [[PH_1]] part.
    for i in range(len(placeholders) - 1, -1, -1):
        result = result.replace(f"[[PH_{i}]]", placeholders[i])
    return result
