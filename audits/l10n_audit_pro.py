#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from core.audit_runtime import load_locale_mapping, load_runtime, project_relative, write_json
from core.usage_scanner import scan_code_usage

LABELS = {
    "en": {
        "title": "Localization Audit Report (Pro)",
        "ar_file": "AR file",
        "en_file": "EN file",
        "code_dir": "Code dirs",
        "summary": "Summary",
        "keys_in_ar": "Keys in ar.json",
        "keys_in_en": "Keys in en.json",
        "keys_detected_in_code": "Keys detected in code",
        "dynamic_usage_count": "Dynamic translation usages",
        "used_keys": "Used keys (code ∩ (AR ∪ EN))",
        "missing_both": "Missing in both language files (code only)",
        "in_ar_not_en": "In AR not EN",
        "in_en_not_ar": "In EN not AR",
        "unused_ar": "Unused in code (AR)",
        "unused_en": "Unused in code (EN)",
        "empty_ar": "Empty translations (AR)",
        "empty_en": "Empty translations (EN)",
        "used_missing_both_title": "Keys used in code but missing from BOTH language files",
        "evidence_sample": "Evidence (sample)",
        "language_mismatch": "Language mismatch",
        "present_in_ar_not_en_title": "Present in AR but missing in EN",
        "present_in_en_not_ar_title": "Present in EN but missing in AR",
        "missing_in_specific_locale": "Keys missing in a specific locale but present in code + other locale",
        "used_in_code_present_en_missing_ar": "Used in code & present in EN, but missing in AR",
        "used_in_code_present_ar_missing_en": "Used in code & present in AR, but missing in EN",
        "unused_keys_title": "Unused keys (present in locale but not detected in code)",
        "unused_in_code_ar": "Unused in code (AR)",
        "unused_in_code_en": "Unused in code (EN)",
        "empty_translations": "Empty translations",
        "empty_in_ar": "Empty in AR",
        "empty_in_en": "Empty in EN",
        "top_used_keys": "Top used keys (by occurrence count)",
        "dynamic_usage_title": "Dynamic translation usages detected in code",
        "none": "_None_",
        "no_occurrences_found": "_No occurrences found._",
        "more": "more",
    },
    "ar": {
        "title": "تقرير تدقيق الترجمة (احترافي)",
        "ar_file": "ملف العربية",
        "en_file": "ملف الإنجليزية",
        "code_dir": "مجلدات الكود",
        "summary": "الملخص",
        "keys_in_ar": "عدد المفاتيح في ar.json",
        "keys_in_en": "عدد المفاتيح في en.json",
        "keys_detected_in_code": "عدد المفاتيح المكتشفة في الكود",
        "dynamic_usage_count": "عدد استخدامات الترجمة الديناميكية",
        "used_keys": "المفاتيح المستخدمة (الكود ∩ (العربية ∪ الإنجليزية))",
        "missing_both": "مفاتيح مفقودة من ملفي اللغة معاً (وموجودة في الكود فقط)",
        "in_ar_not_en": "موجودة في العربية وغير موجودة في الإنجليزية",
        "in_en_not_ar": "موجودة في الإنجليزية وغير موجودة في العربية",
        "unused_ar": "غير مستخدمة في الكود (العربية)",
        "unused_en": "غير مستخدمة في الكود (الإنجليزية)",
        "empty_ar": "ترجمات فارغة (العربية)",
        "empty_en": "ترجمات فارغة (الإنجليزية)",
        "used_missing_both_title": "مفاتيح مستخدمة في الكود لكنها غير موجودة في ملفي اللغة معاً",
        "evidence_sample": "أمثلة من أماكن الاستخدام",
        "language_mismatch": "اختلافات بين ملفي اللغة",
        "present_in_ar_not_en_title": "موجودة في العربية وغير موجودة في الإنجليزية",
        "present_in_en_not_ar_title": "موجودة في الإنجليزية وغير موجودة في العربية",
        "missing_in_specific_locale": "مفاتيح ناقصة في إحدى اللغتين لكنها موجودة في الكود وفي اللغة الأخرى",
        "used_in_code_present_en_missing_ar": "مستخدمة في الكود وموجودة في الإنجليزية لكنها مفقودة من العربية",
        "used_in_code_present_ar_missing_en": "مستخدمة في الكود وموجودة في العربية لكنها مفقودة من الإنجليزية",
        "unused_keys_title": "مفاتيح موجودة في ملفات اللغة لكن لم يتم اكتشاف استخدامها في الكود",
        "unused_in_code_ar": "غير مستخدمة في الكود (العربية)",
        "unused_in_code_en": "غير مستخدمة في الكود (الإنجليزية)",
        "empty_translations": "الترجمات الفارغة",
        "empty_in_ar": "فارغة في العربية",
        "empty_in_en": "فارغة في الإنجليزية",
        "top_used_keys": "أكثر المفاتيح استخداماً",
        "dynamic_usage_title": "استخدامات ترجمة ديناميكية في الكود",
        "none": "_لا يوجد_",
        "no_occurrences_found": "_لم يتم العثور على استخدامات._",
        "more": "أخرى",
    }
}

def is_empty_translation(val) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return len(val.strip()) == 0
    return False

def write_markdown_report(out_path, lang, ar_path, en_path, code_dirs, ar, en, usage_data, runtime):
    L = LABELS[lang]
    occurrences = usage_data["static_occurrences"]
    dynamic_examples = usage_data["dynamic_examples"]
    dynamic_usage_count = int(usage_data["dynamic_usage_count"])
    static_breakdown = usage_data["static_breakdown"]
    dynamic_breakdown = usage_data["dynamic_breakdown"]

    ar_keys = set(ar.keys())
    en_keys = set(en.keys())
    code_keys = set(occurrences.keys())

    in_ar_not_en = sorted(ar_keys - en_keys)
    in_en_not_ar = sorted(en_keys - ar_keys)
    in_code_missing_both = sorted(code_keys - (ar_keys | en_keys))
    in_code_missing_ar = sorted((code_keys & en_keys) - ar_keys)
    in_code_missing_en = sorted((code_keys & ar_keys) - en_keys)
    unused_ar = sorted(ar_keys - code_keys)
    unused_en = sorted(en_keys - code_keys)
    empty_ar = sorted([k for k, v in ar.items() if is_empty_translation(v)])
    empty_en = sorted([k for k, v in en.items() if is_empty_translation(v)])

    usage_counts = sorted(
        ((k, len(v)) for k, v in occurrences.items()),
        key=lambda x: x[1],
        reverse=True
    )

    used_keys = sorted(code_keys & (ar_keys | en_keys))

    def md_list(keys, limit=None):
        if not keys:
            return f"{L['none']}\n"
        shown = keys if limit is None else keys[:limit]
        s = "\n".join([f"- `{k}`" for k in shown]) + "\n"
        if limit is not None and len(keys) > limit:
            s += f"- … (+{len(keys)-limit} {L['more']})\n"
        return s

    def md_occurrences_for_key(k, max_lines=10):
        occ = occurrences.get(k, [])
        if not occ:
            return f"{L['no_occurrences_found']}\n"
        shown = occ[:max_lines]
        s = ""
        for file, ln, line in shown:
            s += f"- `{project_relative(file, runtime)}:{ln}` — `{line}`\n"
        if len(occ) > max_lines:
            s += f"- … (+{len(occ)-max_lines} {L['more']})\n"
        return s

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# {L['title']}\n\n")
        f.write(f"**{L['ar_file']}:** `{project_relative(ar_path, runtime)}`\n\n")
        f.write(f"**{L['en_file']}:** `{project_relative(en_path, runtime)}`\n\n")
        joined_code_dirs = ", ".join(f"`{project_relative(path, runtime)}`" for path in code_dirs)
        f.write(f"**{L['code_dir']}:** {joined_code_dirs}\n\n")
        f.write("---\n\n")

        f.write(f"## {L['summary']}\n\n")
        f.write(f"- {L['keys_in_ar']}: **{len(ar_keys)}**\n")
        f.write(f"- {L['keys_in_en']}: **{len(en_keys)}**\n")
        f.write(f"- {L['keys_detected_in_code']}: **{len(code_keys)}**\n")
        f.write(f"- {L['dynamic_usage_count']}: **{dynamic_usage_count}**\n")
        f.write(f"- {L['used_keys']}: **{len(used_keys)}**\n")
        f.write(f"- {L['missing_both']}: **{len(in_code_missing_both)}**\n")
        f.write(f"- {L['in_ar_not_en']}: **{len(in_ar_not_en)}**\n")
        f.write(f"- {L['in_en_not_ar']}: **{len(in_en_not_ar)}**\n")
        f.write(f"- {L['unused_ar']}: **{len(unused_ar)}**\n")
        f.write(f"- {L['unused_en']}: **{len(unused_en)}**\n")
        f.write(f"- {L['empty_ar']}: **{len(empty_ar)}**\n")
        f.write(f"- {L['empty_en']}: **{len(empty_en)}**\n\n")

        f.write("---\n\n")

        f.write(f"## {L['used_missing_both_title']}\n\n")
        f.write(md_list(in_code_missing_both, limit=200))
        if in_code_missing_both:
            f.write(f"\n### {L['evidence_sample']}\n\n")
            for k in in_code_missing_both[:30]:
                f.write(f"#### `{k}`\n\n")
                f.write(md_occurrences_for_key(k))
                f.write("\n")

        f.write("---\n\n")

        f.write(f"## {L['language_mismatch']}\n\n")
        f.write(f"### {L['present_in_ar_not_en_title']}\n\n")
        f.write(md_list(in_ar_not_en, limit=300))
        f.write(f"\n### {L['present_in_en_not_ar_title']}\n\n")
        f.write(md_list(in_en_not_ar, limit=300))

        f.write("---\n\n")

        f.write(f"## {L['missing_in_specific_locale']}\n\n")
        f.write(f"### {L['used_in_code_present_en_missing_ar']}\n\n")
        f.write(md_list(in_code_missing_ar, limit=200))
        f.write(f"\n### {L['used_in_code_present_ar_missing_en']}\n\n")
        f.write(md_list(in_code_missing_en, limit=200))

        f.write("---\n\n")

        f.write(f"## {L['unused_keys_title']}\n\n")
        f.write(f"### {L['unused_in_code_ar']}\n\n")
        f.write(md_list(unused_ar, limit=400))
        f.write(f"\n### {L['unused_in_code_en']}\n\n")
        f.write(md_list(unused_en, limit=400))

        f.write("---\n\n")

        f.write(f"## {L['empty_translations']}\n\n")
        f.write(f"### {L['empty_in_ar']}\n\n")
        f.write(md_list(empty_ar, limit=400))
        f.write(f"\n### {L['empty_in_en']}\n\n")
        f.write(md_list(empty_en, limit=400))

        f.write("---\n\n")

        f.write(f"## {L['dynamic_usage_title']}\n\n")
        if not dynamic_examples:
            f.write(f"{L['none']}\n")
        else:
            for item in dynamic_examples:
                f.write(
                    f"- `{item['family']}` — `{project_relative(item['file'], runtime)}:{item['line']}` — "
                    f"`{item['text']}`\n"
                )
        f.write("\n---\n\n")

        f.write(f"## {L['top_used_keys']}\n\n")
        if not usage_counts:
            f.write(f"{L['none']}\n")
        else:
            for k, c in usage_counts[:100]:
                f.write(f"- `{k}`: **{c}**\n")
        if static_breakdown:
            f.write("\n### Static families\n\n")
            for family, count in static_breakdown.items():
                f.write(f"- `{family}`: **{count}**\n")
        if dynamic_breakdown:
            f.write("\n### Dynamic families\n\n")
            for family, count in dynamic_breakdown.items():
                f.write(f"- `{family}`: **{count}**\n")

def main():
    runtime = load_runtime(__file__)
    ap = argparse.ArgumentParser()
    ap.add_argument("--ar", default=str(runtime.ar_file))
    ap.add_argument("--en", default=str(runtime.en_file))
    ap.add_argument("--code", nargs="*", default=[str(path) for path in runtime.code_dirs])
    ap.add_argument("--out-en", default=str(runtime.results_dir / "per_tool" / "localization" / "localization_audit_pro_en.md"))
    ap.add_argument("--out-ar", default=str(runtime.results_dir / "per_tool" / "localization" / "localization_audit_pro_ar.md"))
    ap.add_argument("--out-json", default=str(runtime.results_dir / "per_tool" / "localization" / "localization_audit_pro.json"))
    args = ap.parse_args()

    ar_path = Path(args.ar)
    en_path = Path(args.en)
    code_dirs = tuple(Path(item) for item in (args.code or [str(path) for path in runtime.code_dirs]))

    if not ar_path.exists():
        raise SystemExit(f"AR file not found: {ar_path}")
    if not en_path.exists():
        raise SystemExit(f"EN file not found: {en_path}")
    missing_code_dirs = [str(path) for path in code_dirs if not path.exists()]
    if missing_code_dirs:
        raise SystemExit(f"Code dir not found: {', '.join(missing_code_dirs)}")

    ar = load_locale_mapping(ar_path, runtime, runtime.target_locales[0] if runtime.target_locales else "ar")
    en = load_locale_mapping(en_path, runtime, runtime.source_locale)
    locale_key_set = set(ar) | set(en)
    usage_data = scan_code_usage(
        code_dirs,
        runtime.usage_patterns,
        runtime.allowed_extensions,
        profile=runtime.project_profile,
        locale_format=runtime.locale_format,
        locale_keys=locale_key_set,
    )
    occurrences = usage_data["static_occurrences"]

    ar_keys = set(ar.keys())
    en_keys = set(en.keys())
    code_keys = set(occurrences.keys())
    in_ar_not_en = sorted(ar_keys - en_keys)
    in_en_not_ar = sorted(en_keys - ar_keys)
    in_code_missing_both = sorted(code_keys - (ar_keys | en_keys))
    in_code_missing_ar = sorted((code_keys & en_keys) - ar_keys)
    in_code_missing_en = sorted((code_keys & ar_keys) - en_keys)
    unused_ar = sorted(ar_keys - code_keys)
    unused_en = sorted(en_keys - code_keys)
    empty_ar = sorted([k for k, v in ar.items() if is_empty_translation(v)])
    empty_en = sorted([k for k, v in en.items() if is_empty_translation(v)])

    write_markdown_report(Path(args.out_en), "en", ar_path, en_path, code_dirs, ar, en, usage_data, runtime)
    write_markdown_report(Path(args.out_ar), "ar", ar_path, en_path, code_dirs, ar, en, usage_data, runtime)

    findings = []
    for key in in_code_missing_both:
        findings.append({"key": key, "issue_type": "missing_in_both", "locale": "en/ar", "message": "Key is used in code but missing from both locale files."})
    for key in in_code_missing_ar:
        findings.append({"key": key, "issue_type": "missing_in_ar", "locale": "ar", "message": "Key is used in code and present in English, but missing in Arabic."})
    for key in in_code_missing_en:
        findings.append({"key": key, "issue_type": "missing_in_en", "locale": "en", "message": "Key is used in code and present in Arabic, but missing in English."})
    for key in in_ar_not_en:
        findings.append({"key": key, "issue_type": "in_ar_not_en", "locale": "en", "message": "Key exists in Arabic but not in English."})
    for key in in_en_not_ar:
        findings.append({"key": key, "issue_type": "in_en_not_ar", "locale": "ar", "message": "Key exists in English but not in Arabic."})
    for key in unused_ar:
        findings.append({"key": key, "issue_type": "unused_ar", "locale": "ar", "message": "Arabic locale key is not detected in code."})
    for key in unused_en:
        findings.append({"key": key, "issue_type": "unused_en", "locale": "en", "message": "English locale key is not detected in code."})
    for key in empty_ar:
        findings.append({"key": key, "issue_type": "empty_ar", "locale": "ar", "message": "Arabic translation is empty."})
    for key in empty_en:
        findings.append({"key": key, "issue_type": "empty_en", "locale": "en", "message": "English translation is empty."})

    payload = {
        "ar_file": project_relative(ar_path, runtime),
        "en_file": project_relative(en_path, runtime),
        "code_dir": project_relative(code_dirs[0], runtime),
        "code_dirs": [project_relative(path, runtime) for path in code_dirs],
        "counts": {
            "ar_keys": len(ar),
            "en_keys": len(en),
            "code_keys": len(occurrences),
            "dynamic_usage_count": usage_data["dynamic_usage_count"],
            "used_keys": len(set(occurrences) & (set(ar) | set(en))),
            "missing_in_both": len(set(occurrences) - (set(ar) | set(en))),
        },
        "static_breakdown": usage_data["static_breakdown"],
        "dynamic_breakdown": usage_data["dynamic_breakdown"],
        "dynamic_usage_examples": [
            {
                "family": item["family"],
                "file": project_relative(item["file"], runtime),
                "line": item["line"],
                "text": item["text"],
                "expression": item["expression"],
            }
            for item in usage_data["dynamic_examples"]
        ],
        "key_normalizations": usage_data["static_raw_keys"],
        "code_occurrences": {
            k: [{"file": project_relative(f, runtime), "line": ln, "text": t} for f, ln, t in v]
            for k, v in occurrences.items()
        },
        "findings": findings,
    }
    write_json(payload, Path(args.out_json))
    print(f"✅ English report: {args.out_en}")
    print(f"✅ Arabic report:  {args.out_ar}")
    print(f"✅ JSON output:    {args.out_json}")

if __name__ == "__main__":
    main()
