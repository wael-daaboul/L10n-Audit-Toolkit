#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$TOOLS_DIR/.." && pwd)"
LOCALES_DIR="${1:-}"
CODE_DIR="${2:-}"
RESULTS_DIR="$TOOLS_DIR/Results"
REPORT_MD="$RESULTS_DIR/per_tool/basic_localization/localization_report.md"

mkdir -p "$RESULTS_DIR"

python3 - "$TOOLS_DIR" "$LOCALES_DIR" "$CODE_DIR" "$PROJECT_ROOT" "$REPORT_MD" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

tools_dir = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(tools_dir))

from core.audit_runtime import load_locale_mapping, publish_result, load_runtime
from core.usage_scanner import scan_code_usage

locales_arg = sys.argv[2].strip()
code_arg = sys.argv[3].strip()
project_root = Path(sys.argv[4]).resolve()
report_md = Path(sys.argv[5]).resolve()
runtime = load_runtime(tools_dir)

locales_dir = Path(locales_arg).resolve() if locales_arg else runtime.locales_dir
code_dirs = (Path(code_arg).resolve(),) if code_arg else runtime.code_dirs

if runtime.locale_format == "json" and not locales_dir.is_dir():
    locales_dir = runtime.en_file.parent.resolve()
if runtime.locale_format == "json" and not locales_dir.is_dir():
    raise SystemExit(f"ERROR: locales directory not found: {locales_dir}")
missing_code_dirs = [str(path) for path in code_dirs if not path.is_dir()]
if missing_code_dirs:
    raise SystemExit(f"ERROR: code directory not found: {', '.join(missing_code_dirs)}")

ref_json = runtime.en_file if runtime.en_file.exists() else locales_dir / "en.json"
locale_data = load_locale_mapping(ref_json, runtime, runtime.source_locale)

keys = sorted(str(key) for key in locale_data.keys())
key_set = set(keys)
usage_data = scan_code_usage(
    code_dirs,
    runtime.usage_patterns,
    runtime.allowed_extensions,
    profile=runtime.project_profile,
    locale_format=runtime.locale_format,
    locale_keys=key_set,
)
occurrences = usage_data["static_occurrences"]
dynamic_examples = usage_data["dynamic_examples"]
dynamic_usage_count = int(usage_data["dynamic_usage_count"])
static_breakdown = usage_data["static_breakdown"]
dynamic_breakdown = usage_data["dynamic_breakdown"]
missing_keys = sorted(set(occurrences) - key_set)

used_keys = sorted(occurrences.keys(), key=lambda key: (-len(occurrences[key]), key))
unused_keys = sorted(key_set - set(occurrences))
multi_keys = [key for key in used_keys if len(occurrences[key]) > 1]

def relpath(path: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()

report_md.parent.mkdir(parents=True, exist_ok=True)
with report_md.open("w", encoding="utf-8") as handle:
    handle.write("# Localization Audit Report\n\n")
    handle.write(f"**Locales dir:** `{relpath(locales_dir)}`\n\n")
    handle.write("**Code dirs:** " + ", ".join(f"`{relpath(path)}`" for path in code_dirs) + "\n\n")
    handle.write(f"**Reference locale source:** `{relpath(ref_json)}`\n\n")
    handle.write(f"**Dynamic translation usages:** `{dynamic_usage_count}`\n\n")
    handle.write("---\n\n")

    handle.write("## USED KEYS\n\n")
    if used_keys:
        for key in used_keys:
            handle.write(f"- `{key}`: {len(occurrences[key])}\n")
    else:
        handle.write("_No used keys found._\n")
    handle.write("\n---\n\n")

    handle.write("## UNUSED KEYS\n\n")
    if unused_keys:
        for key in unused_keys:
            handle.write(f"- `{key}`\n")
    else:
        handle.write("_No unused keys found._\n")
    handle.write("\n---\n\n")

    handle.write("## MULTIPLE USAGE\n\n")
    if multi_keys:
        for key in multi_keys:
            handle.write(f"- `{key}`: {len(occurrences[key])}\n")
    else:
        handle.write("_No multiple-usage keys._\n")
    handle.write("\n---\n\n")

    handle.write("## STATIC KEYS MISSING IN LOCALE\n\n")
    if missing_keys:
        for key in missing_keys:
            handle.write(f"- `{key}`\n")
    else:
        handle.write("_No missing static keys found._\n")
    handle.write("\n---\n\n")

    handle.write("## DYNAMIC TRANSLATION USAGES\n\n")
    if dynamic_examples:
        for item in dynamic_examples:
            handle.write(f"- `{item['family']}`: {relpath(item['file'])}:{item['line']} {item['text']}\n")
    else:
        handle.write("_No dynamic translation usages found._\n")
    handle.write("\n---\n\n")

    handle.write("## USAGE BREAKDOWN\n\n")
    if static_breakdown:
        handle.write("### Static families\n\n")
        for family, count in static_breakdown.items():
            handle.write(f"- `{family}`: {count}\n")
        handle.write("\n")
    if dynamic_breakdown:
        handle.write("### Dynamic families\n\n")
        for family, count in dynamic_breakdown.items():
            handle.write(f"- `{family}`: {count}\n")
        handle.write("\n")

    handle.write("## USED LOCATIONS (sample)\n\n")
    if used_keys:
        for key in used_keys:
            handle.write(f"## {key}\n\n")
            for file_path, line_number, line in occurrences[key][:15]:
                handle.write(f"- {relpath(file_path)}:{line_number} {line}\n")
            if len(occurrences[key]) > 15:
                handle.write(f"- ... +{len(occurrences[key]) - 15} more\n")
            handle.write("\n")
    else:
        handle.write("_No locations._\n")

publish_result(report_md, runtime, "per_tool", "basic_localization")
print(f"Done. Report generated: {report_md}")
PY
