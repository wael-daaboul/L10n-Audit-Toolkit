# API Documentation

## Overview

The project exposes three API surfaces:

- CLI commands through `l10n-audit`.
- Public Python API through `l10n_audit`.
- Optional FastAPI HTTP reference server in `http_api/server.py`.

The CLI is the primary supported interface. The HTTP API is a reference wrapper and is not required for normal toolkit usage.

## HTTP Endpoint

## Method

GET

## Route

`/health`

## Parameters

None.

## Request Example

```bash
curl http://localhost:8000/health
```

## Response Example

```json
{
  "status": "ok",
  "version": "1.7.1"
}
```

## Errors

- Standard server errors if the service is unavailable.

## Authentication

None in the reference implementation.

## Authorization

None in the reference implementation.

## Related Features

- HTTP service health check.

---

## HTTP Endpoint

## Method

POST

## Route

`/audit/run`

## Parameters

JSON body:

- `project_path` string, required.
- `stage` string, optional, default `full`.
- `ai_enabled` boolean, optional, default `false`.
- `ai_api_key` string, optional.
- `ai_model` string, optional.
- `ai_api_base` string, optional.
- `write_reports` boolean, optional, default `true`.

## Request Example

```json
{
  "project_path": "/absolute/path/to/project",
  "stage": "fast",
  "ai_enabled": false,
  "write_reports": true
}
```

## Response Example

```json
{
  "project_path": "/absolute/path/to/project",
  "stage": "fast",
  "success": true,
  "summary": {
    "total_issues": 0
  }
}
```

The exact response includes the serialized `AuditResult` contract from the public Python API.

## Errors

- `400`: invalid project.
- `422`: invalid AI configuration.
- `500`: audit runtime error.

## Authentication

None in the reference implementation.

## Authorization

None in the reference implementation.

## Related Features

- Audit execution pipeline.
- Optional AI review.
- Report generation.

---

## HTTP Endpoint

## Method

POST

## Route

`/workspace/doctor`

## Parameters

JSON body:

- `project_path` string, required.

## Request Example

```json
{
  "project_path": "/absolute/path/to/project"
}
```

## Response Example

```json
{
  "success": true,
  "framework": "auto",
  "profile": "auto",
  "translation_paths": [],
  "warnings": [],
  "errors": []
}
```

## Errors

- `400`: invalid project.

## Authentication

None in the reference implementation.

## Authorization

None in the reference implementation.

## Related Features

- Workspace health inspection.

---

## HTTP Endpoint

## Method

POST

## Route

`/workspace/init`

## Parameters

JSON body:

- `project_path` string, required.
- `force` boolean, optional, default `false`.
- `channel` string, optional, default `stable`.

## Request Example

```json
{
  "project_path": "/absolute/path/to/project",
  "force": false,
  "channel": "stable"
}
```

## Response Example

```json
{
  "success": true,
  "project_path": "/absolute/path/to/project"
}
```

The exact response mirrors `init_workspace`.

## Errors

- `400`: invalid project.
- `500`: initialization or audit error.

## Authentication

None in the reference implementation.

## Authorization

None in the reference implementation.

## Related Features

- Workspace initialization.

---

## CLI API

### Global Options

- `--version`: show toolkit version.
- `-v`, `--verbose`: show detailed logs.
- `-f`, `--force`: force supported operations.

### Commands

- `l10n-audit init`: initialize workspace.
- `l10n-audit run`: run audit stages.
- `l10n-audit doctor`: inspect workspace discovery and health.
- `l10n-audit update`: refresh existing local workspace.
- `l10n-audit self-update`: show global launcher update guidance.
- `l10n-audit prepare-apply`: freeze approved review rows into `review_final.xlsx`.
- `l10n-audit apply`: apply approved fixes from `review_final.xlsx`.
- `l10n-audit generate-adaptation-report`: create adaptation report from learning profile.
- `l10n-audit generate-manifest`: create consumption manifest from adaptation report.
- `l10n-audit review-manifest`: create reviewed manifest from approvals.
- `l10n-audit apply-manifest`: apply approved manifest actions to configuration.
- `l10n-audit deprecations`: show legacy artifact decommissioning status.

### Supported Run Stages

- `fast`
- `full`
- `grammar`
- `terminology`
- `placeholders`
- `ar-qc`
- `ar-semantic`
- `icu`
- `reports`
- `autofix`
- `ai-review`
- `camel`

## Python API

### `run_audit(project_path, **options)`

Runs an audit stage and returns an `AuditResult`.

### `init_workspace(project_path, **options)`

Initializes a local audit workspace and returns an outcome dictionary.

### `doctor_workspace(project_path)`

Returns a structured workspace health report.

### Public Models

- `AuditResult`
- `AuditIssue`
- `AuditOptions`
- `AuditSummary`
- `ReportArtifact`

### Public Exceptions

- `AuditError`
- `InvalidProjectError`
- `UnsupportedFrameworkError`
- `AIConfigError`
- `ReportWriteError`

## API Security Notes

- Do not expose the reference HTTP API to untrusted networks without authentication and authorization.
- Do not send API keys through logs or persisted artifacts.
- Prefer CI/CD secret stores and environment variables for provider credentials.

