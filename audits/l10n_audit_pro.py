#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import re
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
        "suspicious_usage_count": "Suspicious translation-like usages",
        "used_keys": "Used keys (code ∩ (AR ∪ EN))",
        "confirmed_missing_keys": "Confirmed missing keys",
        "confirmed_unused_keys": "Confirmed unused keys",
        "needs_manual_review": "Needs manual review",
        "empty_ar": "Empty translations (AR)",
        "empty_en": "Empty translations (EN)",
        "used_missing_both_title": "Confirmed missing keys",
        "evidence_sample": "Evidence (sample)",
        "language_mismatch": "Needs manual review",
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
        "suspicious_usage_count": "عدد الاستخدامات المشبوهة الشبيهة بالترجمة",
        "used_keys": "المفاتيح المستخدمة (الكود ∩ (العربية ∪ الإنجليزية))",
        "confirmed_missing_keys": "المفاتيح المفقودة المؤكدة",
        "confirmed_unused_keys": "المفاتيح غير المستخدمة المؤكدة",
        "needs_manual_review": "عناصر تحتاج مراجعة بشرية",
        "empty_ar": "ترجمات فارغة (العربية)",
        "empty_en": "ترجمات فارغة (الإنجليزية)",
        "used_missing_both_title": "المفاتيح المفقودة المؤكدة",
        "evidence_sample": "أمثلة من أماكن الاستخدام",
        "language_mismatch": "عناصر تحتاج مراجعة بشرية",
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
    suspicious_examples = usage_data["suspicious_examples"]
    suspicious_usage_count = int(usage_data["suspicious_usage_count"])
    static_breakdown = usage_data["static_breakdown"]
    dynamic_breakdown = usage_data["dynamic_breakdown"]
    usage_metadata = usage_data.get("usage_metadata", {})

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
    confirmed_missing_keys = sorted(in_code_missing_both + in_code_missing_ar + in_code_missing_en)
    confirmed_unused_keys = sorted(unused_ar + unused_en)
    manual_review_keys = sorted(in_ar_not_en + in_en_not_ar)
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
        f.write(f"- {L['suspicious_usage_count']}: **{suspicious_usage_count}**\n")
        f.write(f"- {L['used_keys']}: **{len(used_keys)}**\n")
        f.write(f"- {L['confirmed_missing_keys']}: **{len(confirmed_missing_keys)}**\n")
        f.write(f"- {L['confirmed_unused_keys']}: **{len(confirmed_unused_keys)}**\n")
        f.write(f"- {L['needs_manual_review']}: **{len(manual_review_keys) + suspicious_usage_count}**\n")
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
        if suspicious_examples:
            f.write(f"\n### {L['dynamic_usage_title']}\n\n")
            for item in suspicious_examples:
                context_suffix = ""
                if item.get("usage_location") and item.get("usage_location") != "unknown":
                    context_suffix = f" [{item['usage_location']}/{item.get('ui_surface', 'generic')}]"
                f.write(
                    f"- `{item['family']}` — `{project_relative(item['file'], runtime)}:{item['line']}` — "
                    f"`{item['text']}`{context_suffix}\n"
                )

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
                context_suffix = ""
                if item.get("usage_location") and item.get("usage_location") != "unknown":
                    context_suffix = f" [{item['usage_location']}/{item.get('ui_surface', 'generic')}]"
                f.write(
                    f"- `{item['family']}` — `{project_relative(item['file'], runtime)}:{item['line']}` — "
                    f"`{item['text']}`{context_suffix}\n"
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
        wrappers=runtime.usage_wrappers,
        accessors=runtime.usage_accessors,
        config_fields=runtime.usage_config_fields,
    )
    occurrences = usage_data["static_occurrences"]
    usage_metadata = usage_data.get("usage_metadata", {})
    suspicious_usage = usage_data["suspicious_usage"]
    dynamic_usage = usage_data["dynamic_usage"]
    suspicious_examples = usage_data["suspicious_examples"]
    dynamic_examples = usage_data["dynamic_examples"]

    ar_keys = set(ar.keys())
    en_keys = set(en.keys())
    code_keys = set(occurrences.keys())
    in_ar_not_en = sorted(ar_keys - en_keys)
    in_en_not_ar = sorted(en_keys - ar_keys)
    in_code_missing_both = sorted(code_keys - (ar_keys | en_keys))
    in_code_missing_ar = sorted((code_keys & en_keys) - ar_keys)
    in_code_missing_en = sorted((code_keys & ar_keys) - en_keys)
    unused_ar_raw = ar_keys - code_keys
    unused_en_raw = en_keys - code_keys
    # Phase 4 & 5: Dynamic Family Inference & Confidence Classification
    dynamic_info = []
    for d in dynamic_examples:
        expr = d.get("expression", "")
        if expr:
            # Normalize expression to regex: "${step}_of_3" -> ".*_of_3"
            p = expr
            p = re.sub(r"\$\{.*?\}", "DOT-STAR", p)
            p = p.replace(" + var + ", "DOT-STAR").replace(" + var", "DOT-STAR").replace("var + ", "DOT-STAR")
            regex_str = f"^{re.escape(p).replace('DOT-STAR', '.*')}$"
            try:
                dynamic_info.append({"rx": re.compile(regex_str), "expr": expr})
            except re.error:
                continue

    def get_confidence_data(key: str) -> dict[str, object]:
        evidence = []
        confidence = 0.0
        patterns = []
        
        # 1. Direct or static-like usage
        if key in occurrences:
            for occ in occurrences[key]:
                fam = occ.get("family", "")
                txt = occ.get("text", "")
                if "static" in fam:
                    confidence = max(confidence, 1.0)
                    evidence.append(f"direct_literal:{txt}")
                elif "accessor" in fam:
                    confidence = max(confidence, 0.95)
                    evidence.append(f"accessor_mapping:{txt}")
                elif "wrapper" in fam:
                    confidence = max(confidence, 0.92)
                    evidence.append(f"wrapper_usage:{txt}")
                elif "config" in fam:
                    confidence = max(confidence, 0.85)
                    evidence.append(f"config_reference:{txt}")
                    
        # 2. Dynamic inference
        for info in dynamic_info:
            if info["rx"].match(key):
                confidence = max(confidence, 0.65)
                evidence.append(f"dynamic_pattern:{info['expr']}")
                patterns.append(info["expr"])
        
        if confidence >= 0.9:
            status = "confirmed_used"
            action = "keep"
        elif confidence >= 0.8:
            status = "likely_used"
            action = "keep"
        elif confidence >= 0.6:
            status = "dynamic_inferred_usage"
            action = "review_before_delete"
        elif confidence > 0:
            status = "uncertain_review_required"
            action = "manual_check"
        else:
            status = "confirmed_unused_key"
            action = "safe_to_delete_after_review"
            
        return {
            "status": str(status),
            "confidence": float(confidence),
            "evidence": list(evidence),
            "patterns": list(patterns),
            "action": str(action)
        }

    unused_ar = []
    unused_en = []
    dynamic_inferred_ar = []
    dynamic_inferred_en = []
    
    # Process all keys to get their confidence data
    all_keys_meta = {}
    for key in (ar_keys | en_keys):
        all_keys_meta[key] = get_confidence_data(key)

    for key in sorted(unused_ar_raw):
        meta = all_keys_meta[key]
        if meta["status"] == "dynamic_inferred_usage":
            dynamic_inferred_ar.append(key)
        elif meta["status"] == "confirmed_unused_key":
            unused_ar.append(key)
        # Other likely_used are already in code_keys or handled by occurrences

    for key in sorted(unused_en_raw):
        meta = all_keys_meta[key]
        if meta["status"] == "dynamic_inferred_usage":
            dynamic_inferred_en.append(key)
        elif meta["status"] == "confirmed_unused_key":
            unused_en.append(key)

    empty_ar = sorted([k for k, v in ar.items() if is_empty_translation(v)])
    empty_en = sorted([k for k, v in en.items() if is_empty_translation(v)])
    confirmed_missing_keys = []
    for key in in_code_missing_both:
        confirmed_missing_keys.append({"key": key, "locale": "en/ar", "issue_type": "missing_in_both"})
    for key in in_code_missing_ar:
        confirmed_missing_keys.append({"key": key, "locale": "ar", "issue_type": "missing_in_ar"})
    for key in in_code_missing_en:
        confirmed_missing_keys.append({"key": key, "locale": "en", "issue_type": "missing_in_en"})
    
    confirmed_unused_keys = (
        [{"key": key, "locale": "ar", "issue_type": "unused_ar"} for key in unused_ar]
        + [{"key": key, "locale": "en", "issue_type": "unused_en"} for key in unused_en]
    )

    dynamic_inferred_usage = (
        [{"key": key, "locale": "ar", "issue_type": "dynamic_inferred_ar"} for key in dynamic_inferred_ar]
        + [{"key": key, "locale": "en", "issue_type": "dynamic_inferred_en"} for key in dynamic_inferred_en]
    )
    needs_manual_review = (
        [{"key": key, "locale": "en", "issue_type": "in_ar_not_en"} for key in in_ar_not_en]
        + [{"key": key, "locale": "ar", "issue_type": "in_en_not_ar"} for key in in_en_not_ar]
        + [
            {
                "key": str(item.get("candidate", "")),
                "locale": "unknown",
                "issue_type": "suspicious_usage",
                "family": item["family"],
                "file": project_relative(item["file"], runtime),
                "line": item["line"],
                "text": item["text"],
            }
            for item in suspicious_usage
        ]
    )
    possibly_dynamic_usage = [
        {
            "expression": item["expression"],
            "family": item["family"],
            "file": project_relative(item["file"], runtime),
            "line": item["line"],
            "text": item["text"],
        }
        for item in dynamic_usage
    ]

    write_markdown_report(Path(args.out_en), "en", ar_path, en_path, code_dirs, ar, en, usage_data, runtime)
    write_markdown_report(Path(args.out_ar), "ar", ar_path, en_path, code_dirs, ar, en, usage_data, runtime)

    findings = []
    
    # Process all keys to get final findings with metadata
    for key in sorted(ar_keys | en_keys | code_keys):
        meta_obj = all_keys_meta.get(key)
        if meta_obj is None:
            # This might be a missing key (used in code but not in JSON)
            meta = get_confidence_data(str(key))
        else:
            meta = meta_obj # type: ignore
            
        # Determine locale status
        locales = []
        if key in ar_keys: locales.append("ar")
        if key in en_keys: locales.append("en")
        locale_str = "/".join(locales) if locales else "none"
        
        # Build finding
        finding = {
            "key": key,
            "locale": locale_str,
            "confidence": meta["confidence"],
            "status": meta["status"],
            "action": meta["action"],
            "evidence": meta["evidence"][:3], # Limit evidence for JSON brevity
            "patterns": meta["patterns"]
        }
        
        # Map to issues
        status = meta["status"]
        if status == "confirmed_unused_key":
            finding["issue_type"] = "unused_ar" if "ar" in locales else "unused_en"
            findings.append(finding)
        elif status == "dynamic_inferred_usage":
            finding["issue_type"] = "dynamic_inferred_usage"
            findings.append(finding)
        elif key in code_keys and not locales:
            finding["issue_type"] = "missing_in_both"
            findings.append(finding)
        elif key in code_keys and "ar" not in locales:
            finding["issue_type"] = "missing_ar"
            findings.append(finding)
        elif key in code_keys and "en" not in locales:
            finding["issue_type"] = "missing_en"
            findings.append(finding)
            
    # Add empty translations
    for key in empty_ar:
        findings.append({"key": key, "issue_type": "empty_ar", "locale": "ar", "message": "Arabic translation is empty."})
    for key in empty_en:
        findings.append({"key": key, "issue_type": "empty_en", "locale": "en", "message": "English translation is empty."})

    # Add suspicious/manual review items (compatibility)
    for item in needs_manual_review:
        findings.append({
            "key": item["key"],
            "issue_type": "needs_manual_review",
            "locale": item["locale"],
            "message": "Manual review required.",
            **{k: v for k, v in item.items() if k not in {"key", "issue_type", "locale"}}
        })


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
            "suspicious_usage_count": usage_data["suspicious_usage_count"],
            "used_keys": len(set(occurrences) & (set(ar) | set(en))),
            "confirmed_missing_keys": len(confirmed_missing_keys),
            "confirmed_unused_keys": len(confirmed_unused_keys),
            "dynamic_inferred_usage": len(dynamic_inferred_usage),
            "needs_manual_review": len(needs_manual_review),
        },
        "static_breakdown": usage_data["static_breakdown"],
        "dynamic_breakdown": usage_data["dynamic_breakdown"],
        "suspicious_breakdown": usage_data["suspicious_breakdown"],
        "confirmed_static_usage": usage_data["confirmed_static_usage"],
        "possibly_dynamic_usage": possibly_dynamic_usage,
        "suspicious_usage_examples": [
            {
                "family": item["family"],
                "file": project_relative(item["file"], runtime),
                "line": item["line"],
                "text": item["text"],
                "candidate": item["candidate"],
                "usage_location": item.get("usage_location", "unknown"),
                "ui_surface": item.get("ui_surface", "generic"),
                "text_role": item.get("text_role", "body"),
            }
            for item in suspicious_examples
        ],
        "dynamic_usage_examples": [
            {
                "family": item["family"],
                "file": project_relative(item["file"], runtime),
                "line": item["line"],
                "text": item["text"],
                "expression": item["expression"],
                "usage_location": item.get("usage_location", "unknown"),
                "ui_surface": item.get("ui_surface", "generic"),
                "text_role": item.get("text_role", "body"),
            }
            for item in dynamic_examples
        ],
        "key_normalizations": usage_data["static_raw_keys"],
        "usage_contexts": usage_data["usage_contexts"],
        "usage_metadata": usage_metadata,
        "confirmed_missing_keys": confirmed_missing_keys,
        "confirmed_unused_keys": confirmed_unused_keys,
        "needs_manual_review": needs_manual_review,
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
