"""
Example FastAPI HTTP API for the L10n Audit Toolkit.

This is an **optional** reference implementation showing how to expose the
l10n_audit Python API over HTTP. It is not required for CLI or programmatic
usage.

Install extras::

    pip install fastapi uvicorn

Run the server::

    cd ./http_api
    uvicorn server:app --reload

Then visit http://localhost:8000/docs for the Swagger UI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException, Body
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    from starlette.concurrency import run_in_threadpool
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "FastAPI and uvicorn are required to run the HTTP API server.\n"
        "Install with: pip install fastapi uvicorn"
    ) from exc

import sys
# Ensure project root on sys.path when running standalone
_here = Path(__file__).parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import l10n_audit

app = FastAPI(
    title="L10n Audit Toolkit API",
    description="HTTP reference API for the L10n Audit Toolkit.",
    version="1.4.0",
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RunAuditRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project root.")
    stage: str = Field("full", description="Audit stage to run.")
    ai_enabled: bool = Field(False, description="Enable AI review step.")
    ai_api_key: str | None = Field(None, description="AI API key (falls back to env).")
    ai_model: str | None = Field(None)
    ai_api_base: str | None = Field(None)
    write_reports: bool = Field(True, description="Write per-tool report files.")


class DoctorRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project root.")


class InitRequest(BaseModel):
    project_path: str = Field(..., description="Absolute path to the project root.")
    force: bool = Field(False, description="Overwrite existing workspace.")
    channel: str = Field("stable", description="Template channel.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.4.0"}


@app.post("/audit/run", tags=["Audit"])
async def run_audit(body: RunAuditRequest) -> Any:
    """Run an audit stage and return structured results.

    This endpoint mirrors :func:`l10n_audit.run_audit`.
    """
    try:
        # Run the heavy audit engine in a threadpool to keep the event loop alive
        result = await run_in_threadpool(
            l10n_audit.run_audit,
            body.project_path,
            stage=body.stage,
            ai_enabled=body.ai_enabled,
            ai_api_key=body.ai_api_key,
            ai_model=body.ai_model,
            ai_api_base=body.ai_api_base,
            write_reports=body.write_reports,
        )
        return JSONResponse(content=result.to_dict())
    except l10n_audit.InvalidProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except l10n_audit.AIConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except l10n_audit.AuditError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/workspace/doctor", tags=["Workspace"])
async def doctor_workspace(body: DoctorRequest) -> Any:
    """Return a health report for the workspace.

    This endpoint mirrors :func:`l10n_audit.doctor_workspace` and returns a
    stable JSON schema containing ``success``, ``framework``, ``profile``,
    ``translation_paths``, ``warnings``, and ``errors``.
    """
    try:
        report = l10n_audit.doctor_workspace(body.project_path)
        return JSONResponse(content=report)
    except l10n_audit.InvalidProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/workspace/init", tags=["Workspace"])
async def init_workspace(body: InitRequest) -> Any:
    """Initialise a new audit workspace in the given project.

    This endpoint mirrors :func:`l10n_audit.init_workspace`.
    """
    try:
        outcome = l10n_audit.init_workspace(
            body.project_path,
            force=body.force,
            channel=body.channel,
        )
        return JSONResponse(content=outcome)
    except l10n_audit.InvalidProjectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except l10n_audit.AuditError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
