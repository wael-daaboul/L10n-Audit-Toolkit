# AGENTS.md — Mandatory Operating Guide

This file is the official entry point for every developer, maintainer, and AI agent working on this repository.

It applies to the entire repository unless a more specific nested `AGENTS.md` file exists. Nested instructions may add stricter local rules, but they must not weaken the rules in this root guide.

Failure to follow this file is a direct violation of the project operating policy.

## Purpose

`AGENTS.md` defines the mandatory workflow that must be followed before modifying the project. It protects the project architecture, documentation quality, audit safety model, and future maintainability.

Documentation is part of the product. A change is not complete unless the related documentation is reviewed and updated.

## Rule 1: Documentation First

Do not modify any project file before reviewing the documentation related to the task.

For any change that affects behavior, architecture, data artifacts, APIs, UI/UX, workflows, or release processes, read these files first:

- `docs/PROJECT_DOCUMENTATION.md`
- `docs/BRS.md`
- `docs/FRS.md`
- `docs/NFR.md`
- `docs/SRS.md`
- `docs/USE_CASES.md`
- `docs/ARCHITECTURE.md`
- `docs/ADR.md`

Also review any task-specific documentation, such as `docs/API.md`, `docs/DATABASE.md`, `docs/UI_UX.md`, `docs/audit_modules.md`, `docs/configuration.md`, or `docs/review_workflow.md`.

## Rule 2: Single Source of Truth

The documentation is the official source of truth for the project.

If code and documentation conflict:

1. Document the conflict.
2. Identify the affected requirement, workflow, API, data artifact, or architecture decision.
3. Propose the safest correction.
4. Do not make architectural decisions based on guessing.

## Rule 3: Understand Before Modifying

Before implementing any change, you must:

1. Understand the problem being solved.
2. Identify the affected files.
3. Identify the system-wide impact.
4. Review dependencies related to the change.
5. Review the impact on data artifacts, APIs, CLI behavior, UI/UX surfaces, generated reports, and apply safety.

Do not patch symptoms when the root cause can be addressed safely.

## Rule 4: Documentation Update Is Mandatory

Every code change must be matched with updates to the relevant documentation.

A task is not complete if code changed but documentation did not.

Examples:

- Feature behavior change: update `docs/FRS.md`, `docs/SRS.md`, `docs/USE_CASES.md`, and `docs/CHANGELOG.md`.
- Architecture change: update `docs/ARCHITECTURE.md`, `docs/ADR.md`, and `docs/CHANGELOG.md`.
- API change: update `docs/API.md` and `docs/CHANGELOG.md`.
- Data artifact or schema change: update `docs/DATABASE.md` and `docs/CHANGELOG.md`.
- CLI/report/review-workbook UX change: update `docs/UI_UX.md` and `docs/CHANGELOG.md`.

## Rule 5: Architecture Preservation

Do not:

- Break the existing architecture.
- Bypass system layers.
- Collapse audit, review, freeze, apply, and reconciliation responsibilities.
- Introduce hacky or temporary solutions without explicit documentation.
- Add technical debt without documenting the reason, impact, and follow-up plan.

Every new architectural decision must be recorded in `docs/ADR.md`.

## Rule 6: Feature Development Workflow

Before adding a new feature:

1. Review `docs/BRS.md`.
2. Review `docs/FRS.md`.
3. Review `docs/NFR.md`.
4. Review `docs/USE_CASES.md`.
5. Review `docs/ARCHITECTURE.md`.
6. Analyze architectural, API, data, CLI, UI/UX, testing, and documentation impact.

After implementing the feature:

1. Update project documentation.
2. Update use cases.
3. Update API documentation if any endpoint, CLI command, public Python API, or contract changed.
4. Update database/data-artifact documentation if schemas, generated files, or persistence behavior changed.
5. Update UI/UX documentation if user-facing flows, reports, workbooks, or terminal output changed.
6. Update `docs/CHANGELOG.md`.

## Rule 7: Database Safety

The project currently uses file-based data artifacts rather than a database server. Any change to persistence, schemas, generated artifacts, workbook contracts, manifests, or data storage must include:

- Reason for the change.
- System impact.
- Migration plan.
- Backward compatibility notes.
- Updates to `docs/DATABASE.md`.
- Updates to `docs/CHANGELOG.md`.

Never silently change artifact contracts such as `audit_master.json`, `review_queue.xlsx`, `review_final.xlsx`, reports, manifests, or `.fix` outputs.

## Rule 8: API Governance

Any new or modified endpoint, CLI command, public Python API function, request/response model, error contract, or authentication/authorization behavior must be documented in `docs/API.md` before the task is considered complete.

API changes must also update related requirements and `docs/CHANGELOG.md`.

## Rule 9: UI/UX Governance

Any user-facing change must include:

- Updates to `docs/UI_UX.md`.
- Updates to affected user flows.
- Updates to affected screens or surfaces.
- Updates to report, CLI, workbook, or Swagger UI descriptions when applicable.

User-facing surfaces include terminal output, Markdown reports, JSON reports, review workbooks, frozen workbooks, generated rejection reports, and the optional HTTP API documentation UI.

## Rule 10: Change Tracking

Every change must be recorded in `docs/CHANGELOG.md`.

Each changelog entry must include:

- Date.
- Description or feature name.
- Modified files.
- Created files.
- Reason for the change.
- System impact.
- Migration notes when relevant.

## Mandatory Startup Checklist

Before starting any task, every agent or developer must complete this checklist:

- [ ] Read `AGENTS.md`.
- [ ] Review `docs/PROJECT_DOCUMENTATION.md`.
- [ ] Review task-relevant documentation.
- [ ] Analyze architectural impact.
- [ ] Identify affected files.
- [ ] Identify documentation that must be updated.
- [ ] Implement the task.
- [ ] Update relevant documentation.
- [ ] Update `docs/CHANGELOG.md`.
- [ ] Perform a final review.

## Completion Criteria

No task is complete unless:

- The requested implementation is complete.
- Related documentation is updated.
- `docs/CHANGELOG.md` is updated.
- Architecture has not been broken.
- Any new architectural decision is documented in `docs/ADR.md`.
- Relevant API, data, and UI/UX documentation is updated.
- Validation or review has been performed where appropriate.
- A final summary is provided with modified files, created files, documentation updates, architectural impact, and future improvements.

## Agent Obligation

Every agent or developer must read this file before executing any task.

`AGENTS.md` is the official operational entry point for understanding project rules and the required workflow.

When in doubt, stop and reconcile the documentation before changing code.

