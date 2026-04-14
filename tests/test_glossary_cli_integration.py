import pytest
import json
from pathlib import Path
from l10n_audit import run_audit

def test_run_audit_with_apply_safe_fixes(tmp_path):
    # Setup mock project
    project = tmp_path / "project"
    project.mkdir()

    # Flutter/GetX profile locale layout
    locales_dir = project / "assets" / "language"
    locales_dir.mkdir(parents=True)

    # Ar file with glossary violation
    ar_file = locales_dir / "ar.json"
    ar_file.write_text(json.dumps({"welcome": "يا زبون"}, ensure_ascii=False), encoding="utf-8")

    # En file contains glossary anchor term
    en_file = locales_dir / "en.json"
    en_file.write_text(json.dumps({"welcome": "Welcome customer"}, ensure_ascii=False), encoding="utf-8")

    # Glossary
    glossary_data = {
        "terms": [{"term_en": "customer", "forbidden_ar": ["زبون"], "approved_ar": "عميل"}],
        "rules": {"forbidden_terms": []},
    }

    # Toolkit config
    ws = project / ".l10n-audit"
    ws.mkdir()
    config_dir = ws / "config"
    config_dir.mkdir()

    # Putting glossary in the tools_dir (.l10n-audit)
    glossary_file = ws / "glossary.json"
    glossary_file.write_text(json.dumps(glossary_data, ensure_ascii=False), encoding="utf-8")

    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "project_profile": "flutter_getx_json",
        "source_locale": "en",
        "target_locales": ["ar"],
        "en_file": "assets/language/en.json",
        "ar_file": "assets/language/ar.json",
        "locales_dir": "assets/language",
        "code_dir": "lib",
        "glossary_file": "glossary.json" # Relative to .l10n-audit
    }), encoding="utf-8")

    # We also need a dummy cli.py for load_runtime to work
    (ws / "cli.py").write_text("# dummy")
    (project / "lib").mkdir(parents=True, exist_ok=True)

    # Run audit with apply_safe_fixes=True
    # We use stage='terminology' to be fast
    result = run_audit(project, stage="terminology", apply_safe_fixes=True)

    assert result.success
    assert len(result.issues) == 1

    # Terminology findings are review-gated; source file should remain untouched.
    assert json.loads(ar_file.read_text(encoding="utf-8"))["welcome"] == "يا زبون"
    # No auto-safe apply artifact is expected for this terminology-only contract.
    fixed_ar_path = locales_dir / "ar.fix.json"
    assert not fixed_ar_path.exists()
