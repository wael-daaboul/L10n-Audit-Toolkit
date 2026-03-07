## Summary

Describe the change and why it is needed.

## Validation

- [ ] `python -m pytest tests`
- [ ] `python -m core.schema_validation --input config/config.json --schema schemas/config.schema.json`
- [ ] `python -m core.schema_validation --input docs/terminology/betaxi_glossary_official.json --schema schemas/glossary.schema.json`
- [ ] `./bin/run_all_audits.sh --stage fast` if audit behavior changed

## Checklist

- [ ] Documentation updated if behavior, commands, or outputs changed
- [ ] Tests added or updated when practical
- [ ] Scope is limited to the stated change
