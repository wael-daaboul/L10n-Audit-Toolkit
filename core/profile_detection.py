from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


LOW_CONFIDENCE_THRESHOLD = 35
AMBIGUITY_MARGIN = 10
MAX_FILE_SAMPLES = 24


@dataclass(frozen=True)
class ProfileCandidate:
    profile_name: str
    project_root: Path
    score: int
    reasons: tuple[str, ...]


FRAMEWORK_FILES: dict[str, tuple[str, ...]] = {
    "flutter_getx_json": ("pubspec.yaml",),
    "laravel_json": ("artisan",),
    "laravel_php": ("artisan",),
    "react_i18next_json": ("package.json",),
    "vue_i18n_json": ("package.json",),
}


USAGE_HINTS: dict[str, tuple[str, ...]] = {
    "flutter_getx_json": (r"\.tr\b", r"\btr\s*\("),
    "laravel_json": (r"__\s*\(", r"@lang\s*\(", r"\btrans\s*\("),
    "laravel_php": (r"__\s*\(", r"@lang\s*\(", r"\btrans\s*\("),
    "react_i18next_json": (r"\bi18n\.t\s*\(", r"(^|[^$A-Za-z0-9_])t\s*\("),
    "vue_i18n_json": (r"\$t\s*\(",),
}


def _resolve_path(base_dir: Path, raw_value: str | None, fallback: Path) -> Path:
    if not raw_value:
        return fallback.resolve()
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve()


def _resolve_roots(base_dir: Path, configured_root: str | None) -> tuple[Path, ...]:
    if configured_root:
        explicit = _resolve_path(base_dir, configured_root, base_dir.parent)
        roots = [explicit]
        if explicit == base_dir.resolve():
            roots.append(base_dir.parent.resolve())
        roots.extend(parent.resolve() for parent in base_dir.parents)
        return tuple(dict.fromkeys(root for root in roots if root.is_dir()))

    roots = [base_dir.resolve(), base_dir.parent.resolve(), *[parent.resolve() for parent in base_dir.parents]]
    return tuple(dict.fromkeys(root for root in roots if root.is_dir()))


def _string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, str))
    if isinstance(value, str):
        return (value,)
    return ()


def _locale_candidates(profile: dict[str, object], locale: str) -> tuple[str, ...]:
    templates = profile.get("locale_path_templates", {})
    if not isinstance(templates, dict):
        return ()
    raw = templates.get(locale) or templates.get("*") or []
    candidates = _string_list(raw)
    return tuple(candidate.replace("{locale}", locale) for candidate in candidates)


def _sample_code_files(project_root: Path, profile: dict[str, object]) -> list[Path]:
    allowed_extensions = _string_list(profile.get("allowed_extensions"))
    code_dirs = _string_list(profile.get("code_dir_candidates"))
    files: list[Path] = []
    seen: set[Path] = set()
    for raw_dir in code_dirs:
        code_dir = (project_root / raw_dir).resolve()
        if not code_dir.is_dir():
            continue
        for path in code_dir.rglob("*"):
            if not path.is_file() or path in seen:
                continue
            if allowed_extensions and not any(path.name.endswith(ext) for ext in allowed_extensions):
                continue
            seen.add(path)
            files.append(path)
            if len(files) >= MAX_FILE_SAMPLES:
                return files
    return files


def score_profile(project_root: Path, profile_name: str, profile: dict[str, object]) -> ProfileCandidate:
    score = 0
    reasons: list[str] = []

    for file_name in FRAMEWORK_FILES.get(profile_name, ()):
        if (project_root / file_name).exists():
            score += 18
            reasons.append(f"found {file_name}")

    raw_markers = profile.get("project_markers", [])
    if isinstance(raw_markers, list):
        for marker_group in raw_markers:
            if isinstance(marker_group, list) and marker_group and all(isinstance(part, str) for part in marker_group):
                if all((project_root / str(part)).exists() for part in marker_group):
                    score += 24
                    reasons.append(f"matched markers: {', '.join(str(part) for part in marker_group)}")

    source_locale = str(profile.get("source_locale") or "en")
    target_locales = _string_list(profile.get("target_locales")) or ("ar",)
    locale_format = str(profile.get("locale_format") or "json")
    for locale in (source_locale, *target_locales):
        for candidate in _locale_candidates(profile, locale):
            candidate_path = (project_root / candidate).resolve()
            if not candidate_path.exists():
                continue
            if locale_format == "laravel_php":
                php_files = sorted(candidate_path.glob("*.php")) if candidate_path.is_dir() else []
                if php_files:
                    score += 30
                    reasons.append(f"found {candidate} with PHP locale files")
                    break
            else:
                score += 26
                reasons.append(f"found locale source {candidate}")
                break

    code_dir_hits = 0
    for raw_dir in _string_list(profile.get("code_dir_candidates")):
        candidate_dir = (project_root / raw_dir).resolve()
        if candidate_dir.is_dir():
            code_dir_hits += 1
            score += 5
            reasons.append(f"found code directory {raw_dir}")
            if code_dir_hits >= 3:
                break

    allowed_extensions = _string_list(profile.get("allowed_extensions"))
    sampled_files = _sample_code_files(project_root, profile)
    if sampled_files and allowed_extensions:
        matched_exts = sorted({ext for ext in allowed_extensions if any(path.name.endswith(ext) for path in sampled_files)})
        if matched_exts:
            score += min(10, len(matched_exts) * 4)
            reasons.append(f"found source files with extensions: {', '.join(matched_exts)}")

    hint_patterns = tuple(re.compile(pattern) for pattern in USAGE_HINTS.get(profile_name, ()))
    if hint_patterns and sampled_files:
        for path in sampled_files:
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in hint_patterns:
                if pattern.search(content):
                    score += 10
                    reasons.append(f"found framework usage hint in {path.name}")
                    hint_patterns = ()
                    break
            if not hint_patterns:
                break

    return ProfileCandidate(
        profile_name=profile_name,
        project_root=project_root,
        score=score,
        reasons=tuple(reasons),
    )


def autodetect_profile(
    base_dir: Path,
    configured_root: str | None,
    profiles: dict[str, dict[str, object]],
) -> tuple[ProfileCandidate, tuple[ProfileCandidate, ...]]:
    candidates: list[ProfileCandidate] = []
    for project_root in _resolve_roots(base_dir, configured_root):
        if not project_root.is_dir():
            continue
        for profile_name, profile in profiles.items():
            candidates.append(score_profile(project_root, profile_name, profile))

    ranked = tuple(sorted(candidates, key=lambda item: (-item.score, len(item.reasons) * -1, item.profile_name)))
    if not ranked:
        raise RuntimeError("No project profile candidates could be evaluated.")
    return ranked[0], ranked
