#!/usr/bin/env python3
from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UsagePatternSpec:
    name: str
    source: str
    family: str
    mode: str


BUILTIN_USAGE_SPECS: dict[str, UsagePatternSpec] = {
    "flutter_getx_tr": UsagePatternSpec("flutter_getx_tr", r"""(['"])(?P<key>[^'"\r\n]+)\1\s*\.tr\b""", "flutter_getx_static", "static"),
    "flutter_getx_tr_dynamic": UsagePatternSpec("flutter_getx_tr_dynamic", r"""\b(?P<expr>[A-Za-z_][A-Za-z0-9_.$>\-?]*)\s*\.tr\b""", "flutter_getx_dynamic", "dynamic"),
    "flutter_tr_call": UsagePatternSpec("flutter_tr_call", r"""(?<![\w.$])tr\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_getx_static", "static"),
    "flutter_tr_call_dynamic": UsagePatternSpec("flutter_tr_call_dynamic", r"""(?<![\w.$])tr\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "flutter_getx_dynamic", "dynamic"),
    "flutter_translate": UsagePatternSpec("flutter_translate", r"""\btranslate\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_translate_static", "static"),
    "flutter_translate_dynamic": UsagePatternSpec("flutter_translate_dynamic", r"""\btranslate\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "flutter_translate_dynamic", "dynamic"),
    "flutter_get_translated": UsagePatternSpec("flutter_get_translated", r"""\bgetTranslated\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_getx_static", "static"),
    "flutter_dot_translate": UsagePatternSpec("flutter_dot_translate", r"""\.translate\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_getx_static", "static"),
    "laravel_custom_translate_static": UsagePatternSpec("laravel_custom_translate_static", r"""\btranslate\s*\(\s*(?:key\s*:\s*)?(['"])(?P<key>[^'"\r\n]+)\1""", "laravel_custom_translate_static", "static"),
    "laravel_custom_translate_dynamic": UsagePatternSpec("laravel_custom_translate_dynamic", r"""\btranslate\s*\(\s*(?:key\s*:\s*)?(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "laravel_custom_translate_dynamic", "dynamic"),
    "laravel_trans_helper": UsagePatternSpec("laravel_trans_helper", r"""\b__\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "laravel_native_static", "static"),
    "laravel_trans_helper_dynamic": UsagePatternSpec("laravel_trans_helper_dynamic", r"""\b__\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "laravel_native_dynamic", "dynamic"),
    "laravel_lang_directive": UsagePatternSpec("laravel_lang_directive", r"""@lang\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "laravel_native_static", "static"),
    "laravel_lang_directive_dynamic": UsagePatternSpec("laravel_lang_directive_dynamic", r"""@lang\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "laravel_native_dynamic", "dynamic"),
    "laravel_trans_function": UsagePatternSpec("laravel_trans_function", r"""\btrans\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "laravel_native_static", "static"),
    "laravel_trans_function_dynamic": UsagePatternSpec("laravel_trans_function_dynamic", r"""\btrans\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "laravel_native_dynamic", "dynamic"),
    "react_t_function": UsagePatternSpec("react_t_function", r"""(?<![\w.$])t\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "react_i18next_static", "static"),
    "react_t_function_dynamic": UsagePatternSpec("react_t_function_dynamic", r"""(?<![\w.$])t\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "react_i18next_dynamic", "dynamic"),
    "react_i18n_t": UsagePatternSpec("react_i18n_t", r"""\bi18n\.t\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "react_i18next_static", "static"),
    "react_i18n_t_dynamic": UsagePatternSpec("react_i18n_t_dynamic", r"""\bi18n\.t\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "react_i18next_dynamic", "dynamic"),
    "vue_t_function": UsagePatternSpec("vue_t_function", r"""\$t\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "vue_i18n_static", "static"),
    "vue_t_function_dynamic": UsagePatternSpec("vue_t_function_dynamic", r"""\$t\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "vue_i18n_dynamic", "dynamic"),
}


DYNAMIC_PATTERN_COMPANIONS = {
    "flutter_getx_tr": ("flutter_getx_tr_dynamic",),
    "flutter_tr_call": ("flutter_tr_call_dynamic",),
    "flutter_translate": ("flutter_translate_dynamic",),
    "laravel_custom_translate_static": ("laravel_custom_translate_dynamic",),
    "laravel_trans_helper": ("laravel_trans_helper_dynamic",),
    "laravel_lang_directive": ("laravel_lang_directive_dynamic",),
    "laravel_trans_function": ("laravel_trans_function_dynamic",),
    "react_t_function": ("react_t_function_dynamic",),
    "react_i18n_t": ("react_i18n_t_dynamic",),
    "vue_t_function": ("vue_t_function_dynamic",),
}


def pattern_from_template(template: str) -> str:
    quote_match = re.search(r"(['\"])KEY\1", template)
    if not quote_match:
        raise ValueError(f"Unsupported usage pattern template: {template}")
    quote = re.escape(quote_match.group(1))
    escaped = re.escape(template)
    escaped = escaped.replace(re.escape(f"{quote_match.group(1)}KEY{quote_match.group(1)}"), rf"{quote}(?P<key>[^'\"\r\n]+){quote}")
    escaped = escaped.replace(r"\ ", r"\s*")
    return escaped


def _build_custom_spec(name: str, source: str) -> UsagePatternSpec:
    mode = "static" if "(?P<key>" in source or "KEY" in source else "dynamic"
    family = f"custom_{mode}"
    return UsagePatternSpec(name=name, source=source, family=family, mode=mode)


def compile_usage_patterns(patterns: tuple[str, ...] | list[str]) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        spec = BUILTIN_USAGE_SPECS.get(pattern)
        source = spec.source if spec else pattern
        if "(?P<key>" not in source and "KEY" in source:
            source = pattern_from_template(source)
        compiled.append(re.compile(source, re.MULTILINE | re.DOTALL))
    return compiled


def compile_usage_specs(patterns: tuple[str, ...] | list[str], include_dynamic: bool = True) -> list[tuple[UsagePatternSpec, re.Pattern[str]]]:
    names: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        if pattern not in seen:
            names.append(pattern)
            seen.add(pattern)
        if include_dynamic:
            for companion in DYNAMIC_PATTERN_COMPANIONS.get(pattern, ()):
                if companion not in seen:
                    names.append(companion)
                    seen.add(companion)

    compiled: list[tuple[UsagePatternSpec, re.Pattern[str]]] = []
    for name in names:
        spec = BUILTIN_USAGE_SPECS.get(name)
        if spec is None:
            source = pattern_from_template(name) if "KEY" in name else name
            spec = _build_custom_spec(name, source)
        compiled.append((spec, re.compile(spec.source, re.MULTILINE | re.DOTALL)))
    return compiled


def matches_extension(path: Path, allowed_extensions: tuple[str, ...] | list[str]) -> bool:
    if not allowed_extensions:
        return True
    as_posix = path.as_posix()
    return any(as_posix.endswith(extension) for extension in allowed_extensions)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _line_number(line_starts: list[int], position: int) -> int:
    return bisect_right(line_starts, position)


def normalize_usage_key(raw_key: str, family: str, profile: str | None, locale_format: str | None, locale_keys: set[str] | None) -> str:
    key = raw_key.strip()
    if not key:
        return key
    if family == "laravel_custom_translate_static" and profile in {"laravel_php", "laravel_json"}:
        if locale_keys:
            prefixed = f"lang.{key}"
            if prefixed in locale_keys and key not in locale_keys:
                return prefixed
        if locale_format == "laravel_php" and locale_keys and f"lang.{key}" in locale_keys:
            return f"lang.{key}"
    return key


def scan_code_usage(
    code_dirs: tuple[Path, ...] | list[Path],
    patterns: tuple[str, ...] | list[str],
    allowed_extensions: tuple[str, ...] | list[str],
    *,
    profile: str | None = None,
    locale_format: str | None = None,
    locale_keys: set[str] | None = None,
) -> dict[str, object]:
    static_occurrences: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    static_raw_keys: dict[str, set[str]] = defaultdict(set)
    static_breakdown: Counter[str] = Counter()
    dynamic_breakdown: Counter[str] = Counter()
    dynamic_usages: list[dict[str, object]] = []
    seen_files: set[Path] = set()
    compiled_specs = compile_usage_specs(patterns)

    for code_dir in code_dirs:
        if not code_dir.exists():
            continue
        for file_path in sorted(path for path in code_dir.rglob("*") if path.is_file()):
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            if not matches_extension(file_path, allowed_extensions):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            starts = _line_starts(content)
            for spec, pattern in compiled_specs:
                for match in pattern.finditer(content):
                    line_number = _line_number(starts, match.start())
                    snippet = content[starts[line_number - 1]: content.find("\n", match.start()) if "\n" in content[match.start():] else len(content)].strip()
                    if spec.mode == "static":
                        raw_key = str(match.group("key")).strip()
                        normalized_key = normalize_usage_key(raw_key, spec.family, profile, locale_format, locale_keys)
                        static_occurrences[normalized_key].append((file_path, line_number, snippet))
                        static_raw_keys[normalized_key].add(raw_key)
                        static_breakdown[spec.family] += 1
                    else:
                        expr = str(match.groupdict().get("expr", "")).strip()
                        if not expr:
                            continue
                        if expr.startswith(("'", '"')):
                            continue
                        if expr.startswith("key:") and expr.split(":", 1)[1].lstrip().startswith(("'", '"')):
                            continue
                        dynamic_usages.append(
                            {
                                "family": spec.family,
                                "file": file_path,
                                "line": line_number,
                                "text": snippet,
                                "expression": expr,
                            }
                        )
                        dynamic_breakdown[spec.family] += 1

    dynamic_examples = [
        {
            "family": item["family"],
            "file": item["file"],
            "line": item["line"],
            "text": item["text"],
            "expression": item["expression"],
        }
        for item in dynamic_usages[:20]
    ]

    return {
        "static_occurrences": static_occurrences,
        "static_breakdown": dict(sorted(static_breakdown.items())),
        "static_raw_keys": {key: sorted(values) for key, values in static_raw_keys.items()},
        "dynamic_usages": dynamic_usages,
        "dynamic_breakdown": dict(sorted(dynamic_breakdown.items())),
        "dynamic_usage_count": len(dynamic_usages),
        "dynamic_examples": dynamic_examples,
    }


def scan_code_keys(
    code_dirs: tuple[Path, ...] | list[Path],
    compiled_patterns: list[re.Pattern[str]],
    allowed_extensions: tuple[str, ...] | list[str],
    key_filter: set[str] | None = None,
) -> dict[str, list[tuple[Path, int, str]]]:
    occurrences: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    seen_files: set[Path] = set()

    for code_dir in code_dirs:
        if not code_dir.exists():
            continue
        for file_path in sorted(path for path in code_dir.rglob("*") if path.is_file()):
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            if not matches_extension(file_path, allowed_extensions):
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            starts = _line_starts(content)
            for pattern in compiled_patterns:
                for match in pattern.finditer(content):
                    if "key" not in match.groupdict():
                        continue
                    key = str(match.group("key")).strip()
                    if key_filter is not None and key not in key_filter:
                        continue
                    line_number = _line_number(starts, match.start())
                    snippet = content[starts[line_number - 1]: content.find("\n", match.start()) if "\n" in content[match.start():] else len(content)].strip()
                    occurrences[key].append((file_path, line_number, snippet))

    return occurrences
