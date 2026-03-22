#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.audit_report_utils import load_all_report_issues, severity_rank, summarize_issues, write_unified_json
from core.audit_runtime import compute_plan_id, compute_text_hash, load_locale_mapping, load_runtime, write_simple_xlsx
from fixes.apply_safe_fixes import build_fix_plan

REVIEW_QUEUE_COLUMNS = [
    "key",
    "locale",
    "old_value",
    "issue_type",
    "suggested_fix",
    "approved_new",
    "status",
    "notes",
    "context_type",
    "context_flags",
    "semantic_risk",
    "lt_signals",
    "review_reason",
    "source_old_value",
    "source_hash",
    "suggested_hash",
    "plan_id",
    "generated_at",
    "provenance",
]
HIDDEN_WHEN_EMPTY = {"placeholders", "icu_message_audit"}


def format_issue(issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity", "info")).upper()
    key = str(issue.get("key", ""))
    source = str(issue.get("source", ""))
    message = str(issue.get("message", ""))
    return f"- [{severity}] `{key}` ({source}) - {message}"


def safe_fix_counts(issues: list[dict[str, Any]]) -> dict[str, int]:
    plan = build_fix_plan(issues)
    return {
        "available": sum(1 for item in plan if item["classification"] == "auto_safe"),
        "review_required": sum(1 for item in plan if item["classification"] == "review_required"),
    }


def priority_order(issues: list[dict[str, Any]]) -> list[str]:
    grouped = Counter(str(issue.get("source", "")) for issue in issues if str(issue.get("severity", "")) in {"critical", "high"})
    if not grouped:
        grouped = Counter(str(issue.get("source", "")) for issue in issues)
    return [source for source, _count in grouped.most_common()]


def recommendations(summary: dict[str, Any], safe_fixes: dict[str, int], review_rows: list[dict[str, str]]) -> list[str]:
    items = []
    if summary["total_issues"]:
        items.append("Start with critical and high-severity issues shown in the dashboard before wording polish.")
    if safe_fixes["available"]:
        items.append("Run `./bin/run_all_audits.sh --stage autofix` to generate auto-safe locale candidates and the safe fix report.")
    if review_rows:
        items.append("Resolve pending items in `Results/review/review_queue.xlsx`, then apply approved rows with `python -m fixes.apply_review_fixes`.")
    return items or ["No action is required because no issues were found."]


def review_locale(issue: dict[str, Any]) -> str:
    locale = str(issue.get("locale", "")).strip()
    source = str(issue.get("source", ""))
    if locale in {"ar", "en"}:
        return locale
    if source in {"ar_locale_qc", "ar_semantic_qc", "terminology"}:
        return "ar"
    if source in {"locale_qc", "grammar"}:
        return "en"
    return locale or "ar"


def old_value_for_issue(issue: dict[str, Any], en_data: dict[str, object], ar_data: dict[str, object]) -> str:
    details = issue.get("details", {})
    explicit = str(details.get("old", ""))
    if explicit:
        return explicit
    locale = review_locale(issue)
    key = str(issue.get("key", ""))
    if locale == "en":
        return str(en_data.get(key, ""))
    if locale == "ar":
        return str(ar_data.get(key, ""))
    return ""


def suggested_fix_for_issue(issue: dict[str, Any], en_data: dict[str, object], ar_data: dict[str, object]) -> str:
    details = issue.get("details", {})
    for field in ("new", "candidate_value", "expected_ar", "use_instead"):
        value = str(details.get(field, ""))
        if value:
            return value

    locale = review_locale(issue)
    issue_type = str(issue.get("issue_type", ""))
    key = str(issue.get("key", ""))
    if issue_type in {"confirmed_missing_key", "missing_in_ar", "in_en_not_ar"} and locale == "ar":
        return str(en_data.get(key, ""))
    if issue_type in {"missing_in_en", "in_ar_not_en"} and locale == "en":
        return str(ar_data.get(key, ""))
    return ""


def build_review_queue(issues: list[dict[str, Any]], runtime) -> list[dict[str, str]]:
    en_data = load_locale_mapping(runtime.en_file, runtime, runtime.source_locale)
    target_locale = runtime.target_locales[0] if runtime.target_locales else "ar"
    ar_data = load_locale_mapping(runtime.ar_file, runtime, target_locale)
    auto_safe = {
        (
            str(item["key"]),
            str(item["locale"]),
            str(item["issue_type"]),
            str(item["candidate_value"]),
        )
        for item in build_fix_plan(issues)
        if item["classification"] == "auto_safe"
    }

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for issue in issues:
        locale = review_locale(issue)
        key = str(issue.get("key", ""))
        issue_type = str(issue.get("issue_type", ""))
        current_value = old_value_for_issue(issue, en_data, ar_data)
        suggested_fix = suggested_fix_for_issue(issue, en_data, ar_data)
        signature = (key, locale, issue_type, suggested_fix)
        if signature in auto_safe or signature in seen:
            continue
        seen.add(signature)
        provenance = {
            "source": str(issue.get("source", "")),
            "issue_type": issue_type,
            "severity": str(issue.get("severity", "")),
            "message": str(issue.get("message", "")),
        }
        rows.append(
            {
                "key": key,
                "locale": locale,
                "old_value": current_value,
                "issue_type": issue_type,
                "suggested_fix": suggested_fix,
                "approved_new": "",
                "status": "pending",
                "notes": str(issue.get("message", "")),
                "context_type": str((issue.get("details", {}) or {}).get("context_type", "")),
                "context_flags": str((issue.get("details", {}) or {}).get("context_flags", "")),
                "semantic_risk": str((issue.get("details", {}) or {}).get("semantic_risk", "")),
                "lt_signals": str((issue.get("details", {}) or {}).get("lt_signals", "")),
                "review_reason": str((issue.get("details", {}) or {}).get("review_reason", "")),
                "source_old_value": current_value,
                "source_hash": compute_text_hash(current_value),
                "suggested_hash": compute_text_hash(suggested_fix),
                "plan_id": compute_plan_id(key, locale, issue_type, current_value, suggested_fix),
                "generated_at": generated_at,
                "provenance": f"{provenance['source']}|{provenance['issue_type']}|{provenance['severity']}",
            }
        )

    rows.sort(key=lambda row: (row["locale"], row["key"], row["issue_type"]))
    return rows


def build_source_status(reports: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, str]:
    counts = Counter(str(issue["source"]) for issue in issues)
    status: dict[str, str] = {}
    for source in sorted(reports):
        if source in HIDDEN_WHEN_EMPTY and counts.get(source, 0) == 0:
            status[source] = "passed"
        else:
            status[source] = f"{counts.get(source, 0)} issues"
    return status


def render_markdown(
    issues: list[dict[str, Any]],
    summary: dict[str, Any],
    safe_fixes: dict[str, int],
    review_rows: list[dict[str, str]],
    source_status: dict[str, str],
    missing: list[str],
) -> str:
    critical_count = sum(1 for issue in issues if str(issue.get("severity")) in {"critical", "high"})
    actionable = [issue for issue in issues if str(issue.get("source")) not in HIDDEN_WHEN_EMPTY or source_status.get(str(issue.get("source"))) != "passed"]
    top_review = sorted(
        actionable,
        key=lambda issue: (
            severity_rank(str(issue.get("severity", "info"))),
            str(issue.get("source", "")),
            str(issue.get("key", "")),
        ),
    )

    lines = [
        "# Final Localization Audit Report",
        "",
        "Workflow: Run Audit -> Open Dashboard -> Review Queue -> Apply Safe Fixes -> Export Final Locale",
        "",
        "## Summary",
        "",
        f"- total issues: **{summary['total_issues']}**",
        f"- critical issues: **{critical_count}**",
        f"- safe fixes available: **{safe_fixes['available']}**",
        f"- review required issues: **{len(review_rows)}**",
        "",
        "## Main Outputs",
        "",
        "- dashboard: `Results/final/final_audit_report.md`",
        "- review queue: `Results/review/review_queue.xlsx`",
        "- final locale: `Results/final_locale/ar.final.json`",
        "",
        "## Review Queue",
        "",
        "Open `Results/review/review_queue.xlsx`, update `approved_new`, then set `status` to `approved` for rows you want to apply.",
        "",
        "## Prioritized Review",
        "",
    ]

    if top_review:
        for issue in top_review[:30]:
            lines.append(format_issue(issue))
    else:
        lines.append("- No actionable issues.")
    lines.append("")

    lines.append("## Audit Status")
    lines.append("")
    for source, status in source_status.items():
        lines.append(f"- {source}: **{status}**")
    lines.append("")

    if missing:
        lines.append("## Missing Reports")
        lines.append("")
        for item in missing:
            lines.append(f"- `{item}`")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    runtime = load_runtime(__file__)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-en", default=str(runtime.results_dir / "final" / "final_audit_report_en.md"))
    parser.add_argument("--out-ar", default=str(runtime.results_dir / "final" / "final_audit_report_ar.md"))
    parser.add_argument("--out-md", default=str(runtime.results_dir / "final" / "final_audit_report.md"))
    parser.add_argument("--out-json", default=str(runtime.results_dir / "final" / "final_audit_report.json"))
    parser.add_argument("--out-normalized", default=str(runtime.results_dir / "normalized" / "aggregated_issues.json"))
    parser.add_argument("--out-review-xlsx", default=str(runtime.results_dir / "review" / "review_queue.xlsx"))
    parser.add_argument("--out-review-json", default=str(runtime.results_dir / "review" / "review_queue.json"))
    parser.add_argument("--sources", default="")
    args = parser.parse_args()

    include_sources = {item.strip() for item in args.sources.split(",") if item.strip()} or None
    reports, issues, missing = load_all_report_issues(runtime.results_dir, include_sources=include_sources)
    summary = summarize_issues(issues)
    safe_fixes = safe_fix_counts(issues)
    review_rows = build_review_queue(issues, runtime)
    source_status = build_source_status(reports, issues)
    markdown = render_markdown(issues, summary, safe_fixes, review_rows, source_status, missing)

    payload = {
        "summary": {
            **summary,
            "critical_issues": sum(1 for issue in issues if str(issue.get("severity")) in {"critical", "high"}),
            "safe_fixes_available": safe_fixes["available"],
            "review_required_issues": len(review_rows),
        },
        "missing_reports": missing,
        "included_sources": sorted(include_sources) if include_sources else sorted(reports.keys()),
        "priority_order": priority_order(issues),
        "recommendations": recommendations(summary, safe_fixes, review_rows),
        "artifacts": {
            "dashboard": "Results/final/final_audit_report.md",
            "review_queue": "Results/review/review_queue.xlsx",
            "final_locale": "Results/final_locale/ar.final.json",
        },
        "workflow": [
            "Run Audit",
            "Open Dashboard",
            "Review Queue",
            "Apply Safe Fixes",
            "Export Final Locale",
        ],
        "source_status": source_status,
        "review_queue": review_rows,
        "issues": issues,
    }

    Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_en).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_ar).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_md).write_text(markdown, encoding="utf-8")
    Path(args.out_en).write_text(markdown, encoding="utf-8")
    Path(args.out_ar).write_text(markdown, encoding="utf-8")
    write_unified_json(Path(args.out_json), payload)
    write_unified_json(Path(args.out_normalized), {"included_sources": payload["included_sources"], "issues": issues})
    write_unified_json(Path(args.out_review_json), {"columns": REVIEW_QUEUE_COLUMNS, "rows": review_rows})
    write_simple_xlsx(review_rows, REVIEW_QUEUE_COLUMNS, Path(args.out_review_xlsx), sheet_name="Review Queue")

    print(f"Done. Aggregated issues: {len(issues)}")
    print(f"Dashboard:   {args.out_md}")
    print(f"Review XLSX: {args.out_review_xlsx}")
    print(f"Review JSON: {args.out_review_json}")
    print(f"JSON:        {args.out_json}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Python API adapter — called by l10n_audit.core.engine
# ---------------------------------------------------------------------------

def run_stage(runtime, options, **kwargs) -> list[ReportArtifact]:
    """Aggregate per-tool reports and write the final dashboard and review queue.

    This calls the same logic as :func:`main` but without argparse.
    Returns a list of :class:`~l10n_audit.models.ReportArtifact` for the
    generated files.
    """
    import logging
    from l10n_audit.models import ReportArtifact
    from core.audit_report_utils import load_all_report_issues  # type: ignore[import]

    logger = logging.getLogger("l10n_audit.report_aggregator")
    results_dir = options.effective_output_dir(runtime.results_dir)

    artifacts: list[ReportArtifact] = []

    try:
        reports, issues, missing = load_all_report_issues(results_dir)
        summary = summarize_issues(issues)
        safe_fixes = safe_fix_counts(issues)
        review_rows = build_review_queue(issues, runtime)
        source_status = build_source_status(reports, issues)
        markdown = render_markdown(issues, summary, safe_fixes, review_rows, source_status, missing)

        include_sources = sorted(reports.keys())
        payload = {
            "summary": {
                **summary,
                "critical_issues": sum(1 for issue in issues if str(issue.get("severity")) in {"critical", "high"}),
                "safe_fixes_available": safe_fixes["available"],
                "review_required_issues": len(review_rows),
            },
            "missing_reports": missing,
            "included_sources": include_sources,
            "priority_order": priority_order(issues),
            "recommendations": recommendations(summary, safe_fixes, review_rows),
            "source_status": source_status,
            "review_queue": review_rows,
            "issues": issues,
        }

        final_dir = results_dir / "final"
        review_dir = results_dir / "review"
        normalized_dir = results_dir / "normalized"

        final_dir.mkdir(parents=True, exist_ok=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        normalized_dir.mkdir(parents=True, exist_ok=True)

        # Write files
        md_file = final_dir / "final_audit_report.md"
        json_file = final_dir / "final_audit_report.json"
        aggr_file = normalized_dir / "aggregated_issues.json"
        review_json = review_dir / "review_queue.json"
        review_xlsx = review_dir / "review_queue.xlsx"

        md_file.write_text(markdown, encoding="utf-8")
        (final_dir / "final_audit_report_en.md").write_text(markdown, encoding="utf-8")
        (final_dir / "final_audit_report_ar.md").write_text(markdown, encoding="utf-8")
        try:
            write_unified_json(json_file, payload)
            write_unified_json(aggr_file, {"included_sources": include_sources, "issues": issues})
            write_unified_json(review_json, {"columns": REVIEW_QUEUE_COLUMNS, "rows": review_rows})
        except Exception as json_exc:
            logger.error("Failed to write unified JSON reports: %s", json_exc)

        artifacts.extend([
            ReportArtifact(name="Final Report (Markdown)", path=str(md_file), format="markdown", category="summary"),
            ReportArtifact(name="Final Report (JSON)", path=str(json_file), format="json", category="summary"),
            ReportArtifact(name="Review Queue (JSON)", path=str(review_json), format="json", category="review"),
        ])

        try:
            write_simple_xlsx(review_rows, REVIEW_QUEUE_COLUMNS, review_xlsx, sheet_name="Review Queue")
            artifacts.append(ReportArtifact(name="Review Queue (Excel)", path=str(review_xlsx), format="xlsx", category="review"))
        except Exception as xlsx_exc:
            logger.warning("Could not write review XLSX: %s", xlsx_exc)

        logger.info("Report aggregator: %d issues aggregated, %d in review queue", len(issues), len(review_rows))
    except Exception as exc:
        logger.warning("Report aggregation failed: %s", exc)

    return artifacts
