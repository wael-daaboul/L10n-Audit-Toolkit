# Security Policy

L10n Audit Toolkit processes localization content, generated reports, and review artifacts. Security issues that could expose translation data, allow unsafe file handling, or weaken review integrity should be reported privately.

## Supported Versions

Security fixes are applied on a best-effort basis to the latest code on the default branch.

## Reporting a Vulnerability

Please do not open a public GitHub issue for suspected security vulnerabilities.

Instead, report the issue privately to the project maintainer with:

- A short description of the issue
- The affected component or file
- Steps to reproduce, if known
- Potential impact
- Any suggested mitigation or patch

Reports should include enough detail for the issue to be reproduced and validated.

## Response Expectations

The maintainer will review reports on a best-effort basis and aim to:

- Confirm whether the issue is reproducible
- Assess impact and scope
- Prepare a fix or mitigation when appropriate
- Coordinate disclosure once a fix is available

## Scope Notes

This project includes bundled third-party assets under `vendor/`. Vulnerabilities in third-party components may need to be addressed by updating the upstream dependency as well as this repository.
