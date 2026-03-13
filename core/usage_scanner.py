#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Iterable
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
    "flutter_translate": UsagePatternSpec("flutter_translate", r"""(?<![\w$.])translate\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_translate_static", "static"),
    "flutter_translate_dynamic": UsagePatternSpec("flutter_translate_dynamic", r"""(?<![\w$.])translate\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "flutter_translate_dynamic", "dynamic"),
    "flutter_get_translated": UsagePatternSpec("flutter_get_translated", r"""\bgetTranslated\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_getx_static", "static"),
    "flutter_dot_translate": UsagePatternSpec("flutter_dot_translate", r"""\.translate\s*\(\s*(['"])(?P<key>[^'"\r\n]+)\1""", "flutter_translate_suspicious", "suspicious"),
    "flutter_dot_translate_dynamic": UsagePatternSpec("flutter_dot_translate_dynamic", r"""\.translate\s*\(\s*(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "flutter_translate_suspicious", "suspicious"),
    "laravel_custom_translate_static": UsagePatternSpec("laravel_custom_translate_static", r"""(?<![\w$.])translate\s*\(\s*(?:key\s*:\s*)?(['"])(?P<key>[^'"\r\n]+)\1""", "laravel_custom_translate_static", "static"),
    "laravel_custom_translate_dynamic": UsagePatternSpec("laravel_custom_translate_dynamic", r"""(?<![\w$.])translate\s*\(\s*(?:key\s*:\s*)?(?!['"])(?P<expr>[^)\r\n]+?)\s*(?:[,)])""", "laravel_custom_translate_dynamic", "dynamic"),
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
    # New patterns for Phase 4: Dynamic Inference
    "dynamic_interpolation_tr": UsagePatternSpec("dynamic_interpolation_tr", r"""(['"])(?P<expr>[^'\"\r\n]*\$\{.*?\}[^'\"\r\n]*)\1\s*\.tr\b""", "dynamic_inference", "dynamic"),
    "dynamic_concat_prefix_tr": UsagePatternSpec("dynamic_concat_prefix_tr", r"""(['"])(?P<prefix>[A-Za-z0-9_-]+)\1\s*\+\s*[A-Za-z_]\w*(?:\s*\.tr\b)?""", "dynamic_inference", "dynamic"),
    "dynamic_concat_suffix_tr": UsagePatternSpec("dynamic_concat_suffix_tr", r"""[A-Za-z_]\w*\s*\+\s*(['"])(?P<suffix>[A-Za-z0-9_-]+)\1(?:\s*\.tr\b)?""", "dynamic_inference", "dynamic"),
    "dynamic_concat_both_tr": UsagePatternSpec("dynamic_concat_both_tr", r"""(['"])(?P<prefix>[A-Za-z0-9_-]+)\1\s*\+\s*[A-Za-z_]\w*\s*\+\s*(['"])(?P<suffix>[A-Za-z0-9_-]+)\3(?:\s*\.tr\b)?""", "dynamic_inference", "dynamic"),
}


DYNAMIC_PATTERN_COMPANIONS = {
    "flutter_getx_tr": ("flutter_getx_tr_dynamic",),
    "flutter_tr_call": ("flutter_tr_call_dynamic",),
    "flutter_translate": ("flutter_translate_dynamic",),
    "flutter_dot_translate": ("flutter_dot_translate_dynamic",),
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


def camel_to_snake(name: str) -> str:
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def compile_accessor_specs(accessors: Iterable[str]) -> list[tuple[UsagePatternSpec, re.Pattern[str]]]:
    compiled: list[tuple[UsagePatternSpec, re.Pattern[str]]] = []
    for name in accessors:
        if not name:
            continue
        # Pattern for ClassName.key or ClassName.key.tr
        source = rf"\b{re.escape(name)}\.(?P<key>[A-Za-z0-9_]+)(?:\.tr)?\b"
        spec = UsagePatternSpec(name=f"accessor_{name}", source=source, family="accessor_static", mode="static")
        compiled.append((spec, re.compile(source, re.MULTILINE | re.DOTALL)))
    
    # Standard S.of(context).key pattern
    s_source = r"\bS\.of\s*\([^)]+\)\.(?P<key>[A-Za-z0-9_]+)\b"
    compiled.append((
        UsagePatternSpec(name="accessor_S", source=s_source, family="accessor_static", mode="static"),
        re.compile(s_source, re.MULTILINE | re.DOTALL)
    ))

    # Standard context.l10n.key pattern
    l10n_source = r"\bcontext\.l10n\.(?P<key>[A-Za-z0-9_]+)\b"
    compiled.append((
        UsagePatternSpec(name="accessor_l10n", source=l10n_source, family="accessor_static", mode="static"),
        re.compile(l10n_source, re.MULTILINE | re.DOTALL)
    ))

    return compiled


def compile_config_specs(fields: Iterable[str]) -> list[tuple[UsagePatternSpec, re.Pattern[str]]]:
    compiled: list[tuple[UsagePatternSpec, re.Pattern[str]]] = []
    for name in fields:
        if not name:
            continue
        # Pattern for "fieldName": "key" or fieldName: "key"
        source = rf"['\"]?{re.escape(name)}['\"]?\s*:\s*(['\"])(?P<key>[^'\"\r\n]+)\1"
        spec = UsagePatternSpec(name=f"config_{name}", source=source, family="config_static", mode="static")
        compiled.append((spec, re.compile(source, re.MULTILINE | re.DOTALL)))
    return compiled


def compile_wrapper_specs(wrappers: Iterable[str]) -> list[tuple[UsagePatternSpec, re.Pattern[str]]]:
    compiled: list[tuple[UsagePatternSpec, re.Pattern[str]]] = []
    for name in wrappers:
        if not name:
            continue
        # Pattern for fn("key")
        source = rf"\b{re.escape(name)}\s*\(\s*(['\"])(?P<key>[^'\"\r\n]+)\1"
        spec = UsagePatternSpec(name=f"wrapper_{name}", source=source, family="wrapper_static", mode="static")
        compiled.append((spec, re.compile(source, re.MULTILINE | re.DOTALL)))
    return compiled


def matches_extension(path: Path, allowed_extensions: tuple[str, ...] | list[str]) -> bool:
    if not allowed_extensions:
        return True
    as_posix = path.as_posix()
    return any(as_posix.endswith(extension) for extension in allowed_extensions)


def infer_usage_location(file_path: Path, snippet: str) -> str:
    return infer_usage_metadata(file_path, snippet)["usage_location"]


def _sentence_shape(snippet: str) -> str:
    stripped = snippet.strip()
    if not stripped:
        return "unknown"
    token_count = len(re.findall(r"[A-Za-z\u0600-\u06FF0-9]+", stripped))
    if "\n" in stripped or token_count >= 7 or any(char in stripped for char in (".", "?", "!", "؟")):
        return "sentence_like"
    if token_count <= 3:
        return "short_label"
    return "phrase"


def infer_usage_metadata(file_path: Path, snippet: str) -> dict[str, str]:
    haystack = f"{file_path.name} {snippet}".lower()
    usage_location = "unknown"
    if any(token in haystack for token in ("snackbar", "flushbar", "scaffoldmessenger")):
        usage_location = "snackbar"
    elif "toast" in haystack:
        usage_location = "toast"
    elif "notification_title" in haystack:
        usage_location = "notification_title"
    elif "notification_body" in haystack or "pushbody" in haystack:
        usage_location = "notification_body"
    elif "subtitle" in haystack:
        usage_location = "subtitle"
    elif "helpertext" in haystack or "helper_text" in haystack or "helper" in haystack:
        usage_location = "helper_text"
    elif "hinttext" in haystack or "placeholder" in haystack:
        usage_location = "form_hint"
    elif "labeltext" in haystack or "formfield" in haystack or "textfield" in haystack:
        usage_location = "form_label"
    elif "alertdialog" in haystack and "title" in haystack:
        usage_location = "dialog_title"
    elif "alertdialog" in haystack or "showdialog" in haystack or "dialog" in haystack or "modal" in haystack:
        usage_location = "dialog_body"
    elif "appbar" in haystack or "title:" in haystack or "screen_title" in haystack:
        usage_location = "title"
    elif any(token in haystack for token in ("elevatedbutton", "textbutton", "outlinedbutton", "iconbutton", "button(")):
        usage_location = "button"

    ui_surface = "generic"
    if usage_location in {"dialog_title", "dialog_body"}:
        ui_surface = "dialog"
    elif usage_location in {"notification_title", "notification_body"}:
        ui_surface = "notification"
    elif usage_location in {"snackbar", "toast"}:
        ui_surface = "feedback"
    elif usage_location in {"form_label", "form_hint", "helper_text"}:
        ui_surface = "form"
    elif usage_location in {"title", "subtitle"}:
        ui_surface = "screen"
    elif usage_location == "button":
        ui_surface = "action"

    text_role = "body"
    if usage_location in {"button", "form_label", "title", "dialog_title", "notification_title"}:
        text_role = "label"
    elif usage_location in {"form_hint", "helper_text", "subtitle", "dialog_body", "notification_body", "snackbar", "toast"}:
        text_role = "message"

    action_hint = "inform"
    if any(token in haystack for token in ("save", "submit", "continue", "next", "retry", "confirm", "approve", "send", "delete", "add", "create", "tap", "click", "press")):
        action_hint = "action"
    elif any(token in haystack for token in ("error", "failed", "warning", "invalid", "required", "success", "done")):
        action_hint = "status"

    audience_hint = "general"
    if any(token in haystack for token in ("driver", "captain", "rider", "customer", "admin", "manager", "user", "passenger")):
        audience_hint = "role_specific"

    return {
        "usage_location": usage_location,
        "ui_surface": ui_surface,
        "text_role": text_role,
        "action_hint": action_hint,
        "audience_hint": audience_hint,
        "sentence_shape": _sentence_shape(snippet),
    }


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
    wrappers: Iterable[str] = (),
    accessors: Iterable[str] = (),
    config_fields: Iterable[str] = (),
) -> dict[str, object]:
    static_occurrences: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
    static_raw_keys: dict[str, set[str]] = defaultdict(set)
    usage_contexts: dict[str, set[str]] = defaultdict(set)
    usage_metadata: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {
            "ui_surfaces": set(),
            "text_roles": set(),
            "action_hints": set(),
            "audience_hints": set(),
            "sentence_shapes": set(),
        }
    )
    static_breakdown: Counter[str] = Counter()
    dynamic_breakdown: Counter[str] = Counter()
    suspicious_breakdown: Counter[str] = Counter()
    dynamic_usages: list[dict[str, object]] = []
    suspicious_usages: list[dict[str, object]] = []
    seen_files: set[Path] = set()
    compiled_specs = compile_usage_specs(patterns)
    compiled_specs.extend(compile_wrapper_specs(wrappers))
    compiled_specs.extend(compile_accessor_specs(accessors))
    compiled_specs.extend(compile_config_specs(config_fields))
    
    # Always include Phase 4 dynamic patterns for inference
    for p in ["dynamic_interpolation_tr", "dynamic_concat_prefix_tr", "dynamic_concat_suffix_tr", "dynamic_concat_both_tr"]:
        spec = BUILTIN_USAGE_SPECS[p]
        compiled_specs.append((spec, re.compile(spec.source, re.MULTILINE | re.DOTALL)))

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
                    metadata = infer_usage_metadata(file_path, snippet)
                    if spec.mode == "static":
                        raw_key = str(match.group("key")).strip()
                        normalized_key = normalize_usage_key(raw_key, spec.family, profile, locale_format, locale_keys)
                        
                        # Handle accessor mapping (camelCase to snake_case)
                        if spec.family == "accessor_static" and locale_keys:
                            if normalized_key not in locale_keys:
                                snake_key = camel_to_snake(normalized_key)
                                if snake_key in locale_keys:
                                    normalized_key = snake_key

                        static_occurrences[normalized_key].append({
                            "file": file_path,
                            "line": line_number,
                            "text": snippet,
                            "family": spec.family,
                        })
                        static_raw_keys[normalized_key].add(raw_key)
                        usage_contexts[normalized_key].add(metadata["usage_location"])
                        usage_metadata[normalized_key]["ui_surfaces"].add(metadata["ui_surface"])
                        usage_metadata[normalized_key]["text_roles"].add(metadata["text_role"])
                        usage_metadata[normalized_key]["action_hints"].add(metadata["action_hint"])
                        usage_metadata[normalized_key]["audience_hints"].add(metadata["audience_hint"])
                        usage_metadata[normalized_key]["sentence_shapes"].add(metadata["sentence_shape"])
                        static_breakdown[spec.family] += 1
                    else:
                        payload = {
                            "family": spec.family,
                            "file": file_path,
                            "line": line_number,
                            "text": snippet,
                            "usage_location": metadata["usage_location"],
                            "ui_surface": metadata["ui_surface"],
                            "text_role": metadata["text_role"],
                            "action_hint": metadata["action_hint"],
                            "audience_hint": metadata["audience_hint"],
                            "sentence_shape": metadata["sentence_shape"],
                        }
                        if spec.mode == "dynamic":
                            groupdict = match.groupdict()
                            expr = str(groupdict.get("expr") or groupdict.get("prefix", "") + " + var + " + groupdict.get("suffix", "")).strip()
                            if groupdict.get("prefix") and not groupdict.get("suffix"):
                                expr = groupdict["prefix"] + " + var"
                            elif groupdict.get("suffix") and not groupdict.get("prefix"):
                                expr = "var + " + groupdict["suffix"]
                                
                            if not expr or expr == "var + ":
                                continue
                            if expr.startswith(("'", '"')):
                                continue
                            if expr.startswith("key:") and expr.split(":", 1)[1].lstrip().startswith(("'", '"')):
                                continue
                            payload["expression"] = expr
                            dynamic_usages.append(payload)
                            dynamic_breakdown[spec.family] += 1
                        else:
                            candidate = str(match.groupdict().get("key") or match.groupdict().get("expr") or "").strip()
                            if not candidate:
                                continue
                            payload["candidate"] = candidate
                            suspicious_usages.append(payload)
                            suspicious_breakdown[spec.family] += 1

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
    suspicious_examples = [
        {
            "family": item["family"],
            "file": item["file"],
            "line": item["line"],
            "text": item["text"],
            "candidate": item["candidate"],
        }
        for item in suspicious_usages[:20]
    ]

    return {
        "confirmed_static_usage": sorted(static_occurrences),
        "static_occurrences": static_occurrences,
        "static_breakdown": dict(sorted(static_breakdown.items())),
        "static_raw_keys": {key: sorted(values) for key, values in static_raw_keys.items()},
        "usage_contexts": {key: sorted(value for value in values if value) for key, values in usage_contexts.items()},
        "usage_metadata": {
            key: {
                "ui_surfaces": sorted(value for value in payload["ui_surfaces"] if value),
                "text_roles": sorted(value for value in payload["text_roles"] if value),
                "action_hints": sorted(value for value in payload["action_hints"] if value),
                "audience_hints": sorted(value for value in payload["audience_hints"] if value),
                "sentence_shapes": sorted(value for value in payload["sentence_shapes"] if value),
            }
            for key, payload in usage_metadata.items()
        },
        "dynamic_usage": dynamic_usages,
        "dynamic_usages": dynamic_usages,
        "dynamic_breakdown": dict(sorted(dynamic_breakdown.items())),
        "dynamic_usage_count": len(dynamic_usages),
        "dynamic_examples": dynamic_examples,
        "suspicious_usage": suspicious_usages,
        "suspicious_breakdown": dict(sorted(suspicious_breakdown.items())),
        "suspicious_usage_count": len(suspicious_usages),
        "suspicious_examples": suspicious_examples,
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
                    occurrences[key].append({
                        "file": file_path,
                        "line": line_number,
                        "text": snippet
                    })

    return occurrences
