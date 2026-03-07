# Roadmap

This roadmap outlines practical next steps for the project. It is intended as a planning guide, not a release commitment.

## Framework and Format Support

- Add Angular i18n support
- Add Android XML string resource support
- Add iOS `.strings` and `.stringsdict` support
- Expand profile templates for more real-world project layouts
- Improve support for multi-locale projects beyond the default source/target pairing

## Audit Quality

- Broaden static usage detection patterns for more framework-specific helper styles
- Improve dynamic translation usage reporting and review guidance
- Expand ICU validation coverage for nested and edge-case message patterns
- Add more terminology validation workflows for project-specific glossaries
- Add more fixture coverage for export round-trips and fix-plan edge cases

## CLI and Developer Experience

- Add a unified Python CLI entry point in addition to shell wrappers
- Improve command help text and discoverability of stage-specific options
- Add explicit configuration validation and troubleshooting output before audit execution
- Add clearer summary output for ambiguous automatic profile detection
- Provide example configuration templates for each supported profile

## CI and Automation

- Add GitHub Actions for test execution and schema validation
- Add CI examples for running fast audits on pull requests
- Publish reusable workflow guidance for teams integrating the toolkit into release checks
- Add artifact upload examples for final reports and fix plans

## Documentation

- Expand framework-specific setup guides in `examples/`
- Add troubleshooting documentation for profile detection and path resolution
- Document report formats and normalized issue shapes in more detail
- Add contribution examples for new project profiles and audit modules
- Improve release packaging and publication readiness for GitHub and PyPI-style distribution
- Improve contributor onboarding and public documentation for first-time users
