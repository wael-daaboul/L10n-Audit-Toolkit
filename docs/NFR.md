# Non-Functional Requirements

## Performance

- The `fast` audit stage should remain suitable for local development and pull-request checks.
- The `full` audit stage may take longer because it includes grammar, ICU, and broader aggregation work.
- AI review must use bounded batching and resilient retry behavior so provider failures do not make deterministic stages unusable.
- Report generation should avoid unnecessary duplicate artifacts by default.
- Large locale sets should be processed through normalized findings and central artifacts rather than repeated manual file scans.

## Security

- API keys and provider credentials must not be stored in generated reports.
- AI credentials should be supplied through environment variables or explicit runtime parameters.
- Apply must validate frozen workbook integrity and source identity before writing fixes.
- Generated `.fix` files must preserve the host framework format and avoid uncontrolled writes.
- Configuration adaptation must require explicit reviewed manifests before changing `config.json`.
- HTTP API usage is optional and should be run in trusted local or secured environments unless additional authentication is added.

## Reliability

- Audit runs should be deterministic for deterministic stages.
- Workspace isolation must prevent audit stages from mutating source files.
- The master artifact must preserve provenance and reconciliation state.
- Apply must be idempotent for the same approved change within a run.
- Hash mismatch, unresolved source lookup, and contract tampering must fail closed.
- Optional dependencies such as AI providers and LanguageTool should degrade gracefully where supported.

## Scalability

- The toolkit must support multiple project profiles and locale formats.
- Audit modules should remain independent so new checks can be added without rewriting the whole pipeline.
- File-based artifacts should remain structured enough for future dashboard, API, or database-backed integrations.
- Configuration profiles and schema validation should support future framework and locale additions.

## Availability

- The CLI must remain usable without the optional HTTP API.
- Deterministic audits must remain usable without AI provider availability.
- Local development workflows should continue to work without network access after dependencies are installed.
- CI/CD execution should fail with actionable messages rather than silent partial success.

## Maintainability

- Audit detection, report projection, apply execution, and reconciliation must remain separate responsibilities.
- Public contracts such as CLI commands, artifact names, workbook schemas, and issue codes should change only with documented migration notes.
- Tests should protect apply safety, artifact contracts, schema behavior, CLI stability, and audit module outputs.
- Documentation must be updated with every change and treated as the source of truth.

## Accessibility

- CLI output should be concise, truthful, and usable in terminals and CI logs.
- Review workbooks should use clear column names and stable fields.
- Markdown reports should be readable without specialized tooling.
- Arabic user guidance should remain available for core workflows.

## Compatibility

- Python 3.10+ is required.
- The toolkit supports JSON locale files and Laravel PHP locale files through dedicated loaders/exporters.
- Supported project examples include Flutter/GetX, Laravel JSON, Laravel PHP, React i18next, and Vue i18n.
- Optional HTTP API requires FastAPI and Uvicorn.
- Grammar checks require Java-compatible LanguageTool when enabled.
- Browser compatibility is relevant only to generated docs/Swagger UI, not the CLI itself.

