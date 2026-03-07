# Project-Specific Assets

The toolkit core is framework- and project-agnostic.

Project-specific content should live outside core logic, for example:
- glossaries
- terminology packs
- allowlists / deny lists
- domain-specific wording rules
- project-specific ignore lists

Current state:
- the Betaxi glossary remains at `docs/terminology/betaxi_glossary_official.json` for backward compatibility

Recommended future layout:
```text
docs/project_assets/
├── betaxi/
│   ├── glossary.json
│   ├── allowlists/
│   └── notes.md
└── <project-name>/
    ├── glossary.json
    ├── allowlists/
    └── notes.md
```
