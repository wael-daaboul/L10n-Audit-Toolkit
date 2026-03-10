# Project-Specific Assets

The toolkit core is framework- and project-agnostic.

Project-specific content should live outside core logic, for example:
- glossaries
- terminology packs
- allowlists / deny lists
- domain-specific wording rules
- project-specific ignore lists

Current state:
- the toolkit accepts any glossary filename as long as `glossary_file` points to it
- `docs/terminology/glossary.json` is the recommended neutral name for new projects
- the repository ships with a small neutral glossary example for demonstration

Recommended future layout:
```text
docs/project_assets/
├── sample-project/
│   ├── glossary.json
│   ├── allowlists/
│   └── notes.md
└── <project-name>/
    ├── glossary.json
    ├── allowlists/
    └── notes.md
```
