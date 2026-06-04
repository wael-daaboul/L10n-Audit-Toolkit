# Software Requirements Specification

## Purpose

This document consolidates the business, functional, and non-functional requirements for L10n Audit Toolkit. It is the official requirements reference and should be read together with:

- `docs/BRS.md`
- `docs/FRS.md`
- `docs/NFR.md`
- `docs/USE_CASES.md`
- `docs/ARCHITECTURE.md`

## Product Scope

L10n Audit Toolkit provides a CLI-first and optionally API-backed workflow for auditing localization files, presenting findings for human review, freezing approved changes, applying safe fixes, and reconciling results into auditable artifacts.

The system does not manage translations as a full translation-management system. It provides quality auditing, review orchestration, and safe application of approved corrections.

## Consolidated Business Requirements

- Detect localization quality risks before release.
- Reduce repetitive manual review work.
- Enforce deterministic, traceable review/apply workflows.
- Keep risky changes human-approved.
- Support CI/CD integration and local developer workflows.
- Support multiple project profiles and locale formats.
- Maintain documentation as the project source of truth.

## Consolidated Functional Requirements

- Initialize a `.l10n-audit/` workspace for a project.
- Discover supported localization layouts.
- Run audit stages through the CLI and public Python API.
- Validate placeholders, terminology, ICU messages, grammar, English source quality, Arabic locale quality, Arabic semantic risks, missing keys, unused keys, and optional CAMeL findings.
- Optionally run AI-assisted review through OpenAI-compatible providers.
- Generate a master artifact and user-facing reports.
- Generate `review_queue.xlsx` for human decisions.
- Freeze approved rows into `review_final.xlsx`.
- Apply only frozen, approved, validated fixes.
- Reconcile apply outcomes into the master state.
- Provide an explicit adaptive manifest workflow for controlled config changes.
- Provide optional HTTP endpoints for health, audit run, workspace doctor, and workspace initialization.

## Consolidated Non-Functional Requirements

- Deterministic behavior for deterministic stages.
- Source-file isolation during audit.
- Fail-closed apply safety.
- Stable public contracts for CLI, API, issue codes, workbooks, and artifacts.
- Optional AI resilience and explicit status reporting.
- Maintainable module separation.
- Test coverage for safety-critical contracts.
- Clear documentation for workflows, artifacts, and architectural decisions.

## Actors

- Developer
- Localization Reviewer
- QA Engineer
- CI/CD System
- Project Owner
- Optional API Client
- Optional AI Provider

## System Inputs

- Project source path.
- Locale files.
- `config.json` and profile defaults.
- Glossary JSON.
- CLI arguments.
- Optional environment variables.
- Optional AI provider credentials.
- Human review decisions in `review_queue.xlsx`.
- Learning profiles and manifest approvals for adaptive workflows.

## System Outputs

- `.l10n-audit/` workspace.
- `Results/artifacts/audit_master.json`.
- `Results/review/review_queue.xlsx`.
- `Results/review/review_final.xlsx`.
- `Results/final/final_audit_report.json`.
- `Results/final/final_audit_report.md`.
- Optional per-tool artifacts.
- Optional `.fix` locale files.
- Optional adaptation, manifest, reviewed manifest, and receipt artifacts.
- Optional HTTP JSON responses.

## Requirement Traceability Matrix

| Requirement | Source | Implemented By | Primary Artifacts |
| :--- | :--- | :--- | :--- |
| Workspace initialization | BRS, FRS | `l10n-audit init`, `init_workspace` | `.l10n-audit/`, `config.json` |
| Audit execution | BRS, FRS | `l10n-audit run`, `run_audit` | `audit_master.json`, reports |
| Human review | BRS, FRS | report aggregation | `review_queue.xlsx` |
| Frozen apply contract | BRS, FRS, NFR | `prepare-apply` | `review_final.xlsx` |
| Safe apply | BRS, FRS, NFR | `apply` and fix modules | `.fix` files, reconciliation data |
| AI-assisted review | FRS, NFR | AI provider and review modules | AI suggestions in review artifacts |
| Adaptive config changes | BRS, FRS | manifest workflow commands | adaptation/manifest artifacts, `config.json` |
| API access | FRS | FastAPI reference server | JSON HTTP responses |
| Documentation governance | BRS, NFR | official docs under `docs/` | updated documentation and changelog |

## Constraints

- Python 3.10+ is required.
- Source locale files must not be mutated during audit stages.
- Apply must not consume editable review queues directly.
- The toolkit uses file artifacts instead of a server database.
- Optional dependencies may be unavailable and must be handled explicitly.
- AI providers are external and cannot be assumed available.

## Assumptions

- Users have access to the project files they audit.
- Reviewers understand the approval workflow before running apply.
- CI/CD users can install Python dependencies and provide required environment variables.
- Locale file formats are supported by existing loaders/exporters or future documented extensions.

## Out of Scope

- Full translation management system features.
- User authentication for the optional HTTP API.
- Hosted SaaS deployment.
- Automatic application of risky semantic translation changes without human review.
- Replacing professional human localization review for ambiguous language decisions.

