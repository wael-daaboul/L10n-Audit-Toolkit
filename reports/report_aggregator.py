#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from core.audit_report_utils import load_all_report_issues, summarize_issues, write_unified_json
from core.audit_runtime import load_runtime

LABELS = {
    "en": {
        "title": "Final Localization Audit Report",
        "executive_summary": "Executive Summary",
        "missing_reports": "Missing Reports",
        "counts_by_source": "Counts By Audit Source",
        "counts_by_severity": "Counts By Severity",
        "counts_by_type": "Counts By Issue Type",
        "priority_order": "Suggested Priority Order",
        "recommendations": "Actionable Recommendations",
        "critical_first": "Critical Issues First",
        "sections": {
            "localization_key_issues": "Localization Key Issues",
            "terminology_violations": "Terminology Violations",
            "placeholder_issues": "Placeholder Issues",
            "icu_message_issues": "ICU Message Issues",
            "grammar_issues": "Grammar Issues",
            "locale_qc_issues": "Locale QC Issues",
            "duplicate_issues": "Possible Duplicate / Suspicious Translation Issues",
        },
    },
    "ar": {
        "title": "التقرير النهائي لتدقيق الترجمة",
        "executive_summary": "الملخص التنفيذي",
        "missing_reports": "التقارير غير المتوفرة",
        "counts_by_source": "العدد حسب مصدر التدقيق",
        "counts_by_severity": "العدد حسب مستوى الخطورة",
        "counts_by_type": "العدد حسب نوع المشكلة",
        "priority_order": "أولوية الإصلاح المقترحة",
        "recommendations": "التوصيات العملية",
        "critical_first": "المشكلات الحرجة أولاً",
        "sections": {
            "localization_key_issues": "مشكلات مفاتيح الترجمة",
            "terminology_violations": "مخالفات المصطلحات",
            "placeholder_issues": "مشكلات العناصر المتغيرة",
            "icu_message_issues": "مشكلات رسائل ICU",
            "grammar_issues": "مشكلات القواعد",
            "locale_qc_issues": "مشكلات فحص جودة النصوص",
            "duplicate_issues": "ترجمات مكررة أو مشبوهة",
        },
    },
}

GROUP_TO_SECTION = {
    "localization_key_issues": "localization_key_issues",
    "terminology_violations": "terminology_violations",
    "placeholder_issues": "placeholder_issues",
    "icu_message_issues": "icu_message_issues",
    "grammar_issues": "grammar_issues",
    "locale_qc_issues": "locale_qc_issues",
}


def format_issue(issue: dict[str, Any]) -> str:
    key = issue.get("key", "")
    severity = str(issue.get("severity", "info")).upper()
    source = issue.get("source", "")
    message = issue.get("message", "")
    return f"- [{severity}] `{key}` ({source}) - {message}"


def build_recommendations(issues: list[dict[str, Any]]) -> list[str]:
    issue_types = Counter(issue["group"] for issue in issues)
    recommendations: list[str] = []
    if issue_types.get("localization_key_issues"):
        recommendations.append("Fix missing keys and empty translations before content polish, because they can break runtime behavior.")
    if issue_types.get("placeholder_issues"):
        recommendations.append("Resolve placeholder mismatches before manual copy edits to avoid interpolation crashes and broken dynamic text.")
    if issue_types.get("icu_message_issues"):
        recommendations.append("Resolve ICU syntax and branch mismatches before release so plural and select logic stays valid in every locale.")
    if issue_types.get("terminology_violations"):
        recommendations.append("Align forbidden or missing approved terms with the glossary to maintain brand consistency across Arabic translations.")
    if issue_types.get("grammar_issues") or issue_types.get("locale_qc_issues"):
        recommendations.append("After structural fixes, apply safe locale cleanups and then review tone-sensitive wording suggestions.")
    return recommendations or ["No actionable recommendations were generated because no issues were found."]


def priority_order(issues: list[dict[str, Any]]) -> list[str]:
    priorities = []
    groups = Counter(issue["group"] for issue in issues if issue["severity"] in {"critical", "high"})
    ordered = sorted(groups.items(), key=lambda item: (-item[1], item[0]))
    for group, _count in ordered:
        priorities.append(group)
    if not priorities:
        priorities = sorted({issue["group"] for issue in issues})
    return priorities


def duplicate_section_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in issues
        if issue["issue_type"] in {
            "duplicate_value",
            "capitalization_inconsistency",
            "ui_wording",
            "inconsistent_translation",
            "similar_phrase_variation",
        }
    ]


def render_markdown(lang: str, issues: list[dict[str, Any]], summary: dict[str, Any], missing: list[str]) -> str:
    labels = LABELS[lang]
    by_group: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        by_group[str(issue["group"])].append(issue)
    by_group["duplicate_issues"] = duplicate_section_issues(issues)

    lines = [f"# {labels['title']}", ""]
    lines.append(f"## {labels['executive_summary']}")
    lines.append("")
    lines.append(f"- Total issues: **{summary['total_issues']}**")
    for severity, count in summary["by_severity"].items():
        lines.append(f"- {severity}: **{count}**")
    lines.append("")

    if missing:
        lines.append(f"## {labels['missing_reports']}")
        lines.append("")
        for item in missing:
            lines.append(f"- `{item}`")
        lines.append("")

    lines.append(f"## {labels['counts_by_source']}")
    lines.append("")
    for source, count in summary["by_source"].items():
        lines.append(f"- {source}: **{count}**")
    lines.append("")

    lines.append(f"## {labels['counts_by_severity']}")
    lines.append("")
    for severity, count in summary["by_severity"].items():
        lines.append(f"- {severity}: **{count}**")
    lines.append("")

    lines.append(f"## {labels['counts_by_type']}")
    lines.append("")
    for issue_type, count in summary["by_issue_type"].items():
        lines.append(f"- {issue_type}: **{count}**")
    lines.append("")

    critical = [issue for issue in issues if issue["severity"] in {"critical", "high"}]
    lines.append(f"## {labels['critical_first']}")
    lines.append("")
    if critical:
        for issue in critical[:50]:
            lines.append(format_issue(issue))
    else:
        lines.append("- None")
    lines.append("")

    for group_key, section_title in labels["sections"].items():
        lines.append(f"## {section_title}")
        lines.append("")
        group_items = by_group.get(group_key, [])
        if group_items:
            for issue in group_items[:100]:
                lines.append(format_issue(issue))
        else:
            lines.append("- None")
        lines.append("")

    lines.append(f"## {labels['priority_order']}")
    lines.append("")
    for item in priority_order(issues):
        lines.append(f"- {item}")
    lines.append("")

    lines.append(f"## {labels['recommendations']}")
    lines.append("")
    for item in build_recommendations(issues):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-en", default=str(runtime.results_dir / "final" / "final_audit_report_en.md"))
    parser.add_argument("--out-ar", default=str(runtime.results_dir / "final" / "final_audit_report_ar.md"))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "final" / "final_audit_report.json"))
    parser.add_argument("--out-normalized", default=str(runtime.results_dir / "normalized" / "aggregated_issues.json"))
    parser.add_argument("--sources", default="")
    args = parser.parse_args()

    include_sources = {item.strip() for item in args.sources.split(",") if item.strip()} or None
    _reports, issues, missing = load_all_report_issues(runtime.results_dir, include_sources=include_sources)
    summary = summarize_issues(issues)
    payload = {
        "summary": summary,
        "missing_reports": missing,
        "included_sources": sorted(include_sources) if include_sources else sorted(_reports.keys()),
        "priority_order": priority_order(issues),
        "recommendations": build_recommendations(issues),
        "issues": issues,
    }

    Path(args.out_en).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_ar).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_en).write_text(render_markdown("en", issues, summary, missing), encoding="utf-8")
    Path(args.out_ar).write_text(render_markdown("ar", issues, summary, missing), encoding="utf-8")
    write_unified_json(Path(args.out_json), payload)
    write_unified_json(Path(args.out_normalized), {"included_sources": payload["included_sources"], "issues": issues})

    print(f"Done. Aggregated issues: {len(issues)}")
    print(f"EN:   {args.out_en}")
    print(f"AR:   {args.out_ar}")
    print(f"JSON: {args.out_json}")


if __name__ == "__main__":
    main()
