# Changelog

## v1.2.1
**Arabic Protection, API Stability, and Reliability**

- **Local API Stability**: Implemented non-blocking `run_audit` in `server.py` using `run_in_threadpool` for better UI responsiveness.
- **Arabic Placeholder Protection**: Enhanced `ar_locale_qc` with a robust masking system to prevent accidental corruption of variables and numbers during text cleanup.
- **Graceful Error Handling**: Added independent `try-except` wrappers around audit modules to ensure a single diagnostic failure doesn't halt the entire process.
- **Auto-Cleanup**: Automated cleaning of `Results/` temporary directories before each run to prevent data pollution.
- **Improved Validation**: Added explicit `InvalidProjectError` raising for better API integration and error reporting.
- **Documentation**: Added Arabic usage guide ([USAGE_AR.md](USAGE_AR.md)) and Local HTTP API documentation.

## v1.2.0

**Major Architectural Refactor and Official Python API**

- **CLI-to-Library Transformation**: Extracted the core audit logic from the CLI into a standalone Python package (`l10n_audit`).
- **Official Python API**: Added `l10n_audit.run_audit()`, `init_workspace()`, and `doctor_workspace()` for programmatic use.
- **In-Process Engine**: Audits now run directly in the Python process (no `subprocess` overhead).
- **Structured Data Models**: Introduced `AuditResult`, `AuditIssue`, and `AuditSummary` dataclasses with stable JSON/Dict serialization.
- **Machine-Readable Codes**: Added stable `code` identifiers to all issues (e.g., `MISSING_KEY`, `TERMINOLOGY_VIOLATION`).
- **AI Provider Interface**: Cleanly decoupled AI review logic with an injectable `AIProvider` protocol.
- **Reference HTTP API**: Added a FastAPI-based reference implementation in `http_api/`.
- **Packaging Improvements**: Switched to `pyproject.toml` for modern builds (builds both `sdist` and `wheel`).
- **CI/CD Enhancements**: Updated GitHub Actions to use modular builds and automated release flows.

## v1.0

Initial public release of L10n Audit Toolkit.

Project maturity at this stage:

- production-oriented for the currently supported profiles and formats
- actively maintained
- still expanding framework coverage, automation, and documentation depth

See [ROADMAP.md](ROADMAP.md) for planned improvements.
