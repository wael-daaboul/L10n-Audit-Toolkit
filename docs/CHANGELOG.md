# Documentation Change Log

## Date

2026-06-05

## Feature

GitHub-safe ignore policy.

## Modified Files

- `.gitignore`
- `docs/PROJECT_DOCUMENTATION.md`
- `docs/CHANGELOG.md`

## Created Files

- None.

## Reason

Harden repository hygiene before GitHub upload by excluding local secrets, private configuration, generated audit artifacts, cache directories, virtual environments, logs, bundled vendor tools, and machine-specific files while allowing project documentation to be tracked.

## Impact

- Reduces risk of uploading credentials, API keys, local workspaces, generated reports, and bulky dependencies.
- Stops ignoring `docs/architecture/` so architecture documentation can be version-controlled.
- Keeps examples and official documentation eligible for GitHub publication.

## Migration Notes

- `.gitignore` does not untrack files already committed to Git. If `config/config.json` should be removed from Git history or the index, run `git rm --cached config/config.json` after confirming it is safe.

---

## Date

2026-06-04

## Feature

Root operating guide for developers and AI agents.

## Modified Files

- `docs/PROJECT_DOCUMENTATION.md`
- `docs/CHANGELOG.md`

## Created Files

- `AGENTS.md`

## Reason

Define the mandatory repository entry point and operating policy for all future developers and AI agents, including documentation-first work, single source of truth rules, architecture governance, API/data/UI governance, and completion criteria.

## Impact

- Adds a repository-wide mandatory workflow before any future modification.
- Makes documentation review and changelog updates explicit completion requirements.
- Documents how future agents must preserve architecture and update affected documentation.

## Migration Notes

- No runtime or data migration is required.
- Future tasks must start by reading `AGENTS.md` and task-relevant documentation.

---

## Date

2026-06-04

## Feature

Canonical documentation baseline.

## Modified Files

- None.

## Created Files

- `docs/PROJECT_DOCUMENTATION.md`
- `docs/BRS.md`
- `docs/FRS.md`
- `docs/NFR.md`
- `docs/SRS.md`
- `docs/USE_CASES.md`
- `docs/USE_CASE_DIAGRAM.md`
- `docs/ARCHITECTURE.md`
- `docs/ADR.md`
- `docs/DATABASE.md`
- `docs/API.md`
- `docs/UI_UX.md`
- `docs/CHANGELOG.md`

## Reason

Establish the required documentation-first structure and create a single official reference set for project requirements, architecture, APIs, data artifacts, use cases, UI/UX, and future changes.

## Impact

- Adds formal requirement and architecture documentation without changing runtime code.
- Defines the documentation baseline that future development must update.
- Clarifies that existing docs remain supporting references while the new files provide the official structure requested by project policy.

## Migration Notes

- No code or data migration is required.
- Future feature work must update the relevant official docs and append a new entry to this changelog.
