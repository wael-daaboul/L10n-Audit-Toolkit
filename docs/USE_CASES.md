# Use Cases Documentation

## Use Case ID

UC-001

## Title

Initialize Audit Workspace

## Actors

- Developer
- QA Engineer

## Preconditions

- Project path exists.
- User has write access to the project workspace.

## Main Flow

1. Actor runs `l10n-audit init`.
2. System detects project profile and locale layout.
3. System creates `.l10n-audit/` and default configuration.
4. System reports initialization status.

## Alternative Flow

- Actor passes `--force` to overwrite or refresh existing workspace data.

## Exception Flow

- Invalid project path causes initialization failure.
- Existing workspace conflict fails unless overwrite is explicit.

## Post Conditions

- Project contains a usable audit workspace.

## Business Rules

- Source locale files are not modified.
- Configuration must be schema-compatible.

## Related Screens

- CLI terminal output.

## Related APIs

- CLI: `l10n-audit init`
- Python: `init_workspace`
- HTTP: `POST /workspace/init`

---

## Use Case ID

UC-002

## Title

Inspect Workspace Health

## Actors

- Developer
- QA Engineer
- CI/CD System

## Preconditions

- Project path exists.

## Main Flow

1. Actor runs `l10n-audit doctor`.
2. System inspects project profile, locale paths, and workspace readiness.
3. System returns warnings, errors, and detected paths.

## Alternative Flow

- Actor includes `--check-ai` to inspect AI readiness.

## Exception Flow

- Invalid path or broken configuration is reported as an error.

## Post Conditions

- Actor has a diagnostic status report.

## Business Rules

- Doctor must not mutate source files.

## Related Screens

- CLI terminal output.

## Related APIs

- CLI: `l10n-audit doctor`
- Python: `doctor_workspace`
- HTTP: `POST /workspace/doctor`

---

## Use Case ID

UC-003

## Title

Run Localization Audit

## Actors

- Developer
- QA Engineer
- CI/CD System

## Preconditions

- Workspace is initialized or project has valid configuration.
- Locale files exist.

## Main Flow

1. Actor runs `l10n-audit run --stage <stage>`.
2. System validates stage and configuration.
3. System isolates locale files.
4. System runs selected audit modules.
5. System aggregates results.
6. System writes reports and review queue artifacts.

## Alternative Flow

- Actor enables AI review.
- Actor supplies custom glossary or output path.
- Actor uses `fast`, `full`, or a single audit stage.

## Exception Flow

- Invalid stage fails before execution.
- Missing AI credentials fail AI-enabled execution.
- Runtime configuration errors stop the audit.

## Post Conditions

- Results exist under `Results/`.
- Source files remain unchanged.

## Business Rules

- Audit stages must not directly modify source locale files.
- Findings must be normalized before review projection.

## Related Screens

- CLI terminal output.
- Final Markdown report.

## Related APIs

- CLI: `l10n-audit run`
- Python: `run_audit`
- HTTP: `POST /audit/run`

---

## Use Case ID

UC-004

## Title

Review Findings

## Actors

- Localization Reviewer
- QA Engineer

## Preconditions

- `Results/review/review_queue.xlsx` exists.

## Main Flow

1. Actor opens `review_queue.xlsx`.
2. Actor reviews source, target, issue type, and suggestion.
3. Actor approves, rejects, or edits proposed values.
4. Actor saves review decisions.

## Alternative Flow

- Actor reviews final Markdown report before editing workbook decisions.

## Exception Flow

- Missing review queue requires rerunning report generation or audit.

## Post Conditions

- Review queue contains human decisions ready for freezing.

## Business Rules

- Editable review queue is not an apply contract.
- Ambiguous findings require human approval.

## Related Screens

- Spreadsheet review workbook.
- Final Markdown report.

## Related APIs

- Generated artifact: `review_queue.xlsx`

---

## Use Case ID

UC-005

## Title

Freeze Approved Rows

## Actors

- Developer
- Localization Reviewer

## Preconditions

- `review_queue.xlsx` exists and contains review decisions.

## Main Flow

1. Actor runs `l10n-audit prepare-apply`.
2. System validates approved rows.
3. System rejects invalid rows with explanations.
4. System writes `review_final.xlsx`.

## Alternative Flow

- Actor supplies custom input, output, or rejection-report paths.

## Exception Flow

- Invalid workbook schema fails contract generation.
- Stale or unresolved rows are rejected.

## Post Conditions

- `review_final.xlsx` exists as the frozen execution contract.

## Business Rules

- Only approved and valid rows may enter the frozen contract.
- `review_final.xlsx` must not be manually edited.

## Related Screens

- CLI terminal output.
- Rejection report when generated.

## Related APIs

- CLI: `l10n-audit prepare-apply`

---

## Use Case ID

UC-006

## Title

Apply Approved Fixes

## Actors

- Developer
- CI/CD System

## Preconditions

- `review_final.xlsx` exists.
- Locale format is supported by exporters.

## Main Flow

1. Actor runs `l10n-audit apply`.
2. System reads only `review_final.xlsx`.
3. System validates hashes and approved values.
4. System writes `.fix` locale files.
5. System reconciles apply status into master artifacts.

## Alternative Flow

- Actor supplies custom frozen workbook path.
- Actor uses `--all` only for explicit forced behavior where supported.

## Exception Flow

- Missing `review_final.xlsx` blocks apply.
- Hash mismatch or tampered approved value blocks affected rows.
- Unsupported locale format fails with an explicit error.

## Post Conditions

- Approved fixes are represented as framework-compatible fix outputs.
- Master state reflects apply reconciliation.

## Business Rules

- Apply must never read from `review_queue.xlsx`.
- Apply must fail closed on stale, unresolved, or tampered data.

## Related Screens

- CLI terminal output.

## Related APIs

- CLI: `l10n-audit apply`

---

## Use Case ID

UC-007

## Title

Run Optional AI Review

## Actors

- Developer
- Localization Reviewer

## Preconditions

- AI review is enabled.
- Provider credentials are available.

## Main Flow

1. Actor runs audit with AI settings.
2. System validates provider configuration.
3. System sends eligible review items to provider.
4. System validates suggestions.
5. System exposes suggestions for human review.

## Alternative Flow

- Actor configures custom API base, provider, or model.

## Exception Flow

- Missing credentials return AI configuration errors.
- Provider failures are reported without bypassing deterministic safety.

## Post Conditions

- AI suggestions are available in review artifacts when successful.

## Business Rules

- AI suggestions are never applied without human review, freeze, and apply validation.

## Related Screens

- CLI terminal output.
- Review workbook.
- AI usage documentation.

## Related APIs

- CLI: `l10n-audit run --ai-enabled`
- Python: `run_audit(..., ai_enabled=True)`
- HTTP: `POST /audit/run`

---

## Use Case ID

UC-008

## Title

Apply Reviewed Configuration Manifest

## Actors

- Project Owner
- Developer

## Preconditions

- Learning profile exists.
- Manifest approvals are explicitly provided.

## Main Flow

1. Actor generates an adaptation report.
2. Actor generates a consumption manifest.
3. Actor reviews manifest actions through approvals JSON.
4. Actor builds a reviewed manifest.
5. Actor applies approved manifest actions to configuration.

## Alternative Flow

- Actor uses explicit output paths for report and manifests.

## Exception Flow

- Missing report, manifest, or approvals file blocks progress.
- Unapproved actions are ignored.

## Post Conditions

- Approved configuration changes are applied.
- Changes are traceable to reviewed manifest data.

## Business Rules

- Adaptive changes must never auto-apply without explicit reviewed approval.

## Related Screens

- CLI terminal output.
- JSON manifest files.

## Related APIs

- CLI: `generate-adaptation-report`, `generate-manifest`, `review-manifest`, `apply-manifest`

---

## Use Case ID

UC-009

## Title

Run Audit in CI/CD

## Actors

- CI/CD System
- QA Engineer

## Preconditions

- Dependencies are installed.
- Project configuration is present.

## Main Flow

1. CI job runs a chosen audit stage.
2. System produces deterministic output.
3. CI job stores or checks reports.
4. Release gate uses audit outcome.

## Alternative Flow

- Nightly jobs enable AI review where credentials are available.

## Exception Flow

- Missing dependencies or invalid configuration fail the CI job.

## Post Conditions

- CI has a localization quality signal and artifacts.

## Business Rules

- CI execution should prefer deterministic stages for pull requests.
- AI-enabled CI should be explicit and credential-managed.

## Related Screens

- CI logs.
- Generated reports.

## Related APIs

- CLI: `l10n-audit run`

---

## Use Case ID

UC-010

## Title

Use HTTP Reference API

## Actors

- Optional API Client
- Developer

## Preconditions

- FastAPI and Uvicorn are installed.
- HTTP server is running.

## Main Flow

1. Actor calls `/health`.
2. Actor calls workspace or audit endpoint.
3. System delegates to public Python API.
4. System returns JSON response.

## Alternative Flow

- Actor visits `/docs` for FastAPI Swagger UI.

## Exception Flow

- Invalid project returns HTTP 400.
- AI config errors return HTTP 422.
- audit runtime errors return HTTP 500.

## Post Conditions

- API client receives structured JSON output.

## Business Rules

- HTTP API is optional and mirrors core Python behavior.
- Authentication is not built in and must be added for untrusted deployments.

## Related Screens

- Swagger UI.
- API client output.

## Related APIs

- `GET /health`
- `POST /audit/run`
- `POST /workspace/doctor`
- `POST /workspace/init`

