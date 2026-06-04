# Business Requirements Specification

## Business Goals

- Improve release confidence for multilingual products by detecting localization issues before production.
- Reduce manual QA effort for localization teams by automating repetitive checks.
- Preserve human control over risky translation changes through explicit review and frozen apply contracts.
- Support developer adoption through a CLI-first workflow that can run locally or in CI/CD.
- Provide audit artifacts that can be shared between developers, translators, QA, and management.

## Business Value

- Fewer production localization regressions.
- Lower review cost for large translation sets.
- Faster feedback loops for missing keys, placeholder drift, terminology violations, ICU issues, and Arabic quality issues.
- Clear accountability through review queues, final apply workbooks, reports, and master-state reconciliation.
- Repeatable CI/CD integration for localization readiness checks.

## Problems Solved

- Translation keys missing in one locale but present in another.
- Placeholder loss, renaming, or formatting drift.
- Inconsistent terminology and forbidden term usage.
- Arabic UI text issues such as mixed script, suspicious literal translations, spacing, punctuation, and semantic mismatch.
- Grammar and spelling issues in source locale content.
- Risky direct application of unreviewed translation changes.
- Fragmented audit outputs without a central traceable source of truth.

## Stakeholders

- **Project owner:** defines quality targets, supported locale formats, release expectations, and roadmap priorities.
- **Localization users:** review findings, approve corrections, maintain glossary terms, and verify translation quality.
- **Developers:** configure the toolkit, run audits, integrate results into CI/CD, and apply approved fixes.
- **QA teams:** validate localization readiness and inspect final reports before release.
- **Management:** monitors quality trends, review effort, and release risk.
- **External parties:** translators, language reviewers, AI service providers, and optional LanguageTool/CAMeL tooling providers.

## Business Rules

- Audit execution must not directly modify source locale files.
- Apply must consume only the frozen `review_final.xlsx` contract.
- `review_queue.xlsx` is editable by humans; `review_final.xlsx` is not manually editable.
- Risky or ambiguous findings must be routed to manual review.
- AI review is optional and must not replace deterministic safety gates.
- Source identity validation must block stale or tampered rows before apply.
- Configuration adaptation must require an explicit manifest review workflow before modifying `config.json`.
- Generated artifacts must preserve provenance, decisions, and reconciliation status.
- Documentation is part of the product and must be updated with every functional, architectural, data, API, or UI change.

## Success Criteria

- Audit runs produce deterministic reports for the same inputs and configuration.
- Human reviewers can identify, approve, reject, and freeze changes without editing source files directly.
- Apply rejects stale or tampered rows and only applies approved changes.
- CLI workflows remain scriptable for CI/CD.
- Optional AI review clearly reports status and preserves review safety.
- Generated artifacts are understandable and traceable.
- Documentation remains aligned with current code behavior and release workflow.

## KPIs

- Number of localization issues detected before release.
- Percentage of approved fixes applied without manual source-file editing.
- False-positive rate for review-required findings.
- Number of stale/tampered apply rows rejected.
- Audit execution duration by stage and project size.
- CI/CD localization check adoption rate.
- Documentation coverage for new features and workflows.

