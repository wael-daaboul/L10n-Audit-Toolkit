import pytest
import pytest
import json
from pathlib import Path
from l10n_audit import run_audit

@pytest.mark.skip(reason="Profile registration pending")
def test_run_audit_with_apply_safe_fixes(tmp_path):
    # Setup mock project
    project = tmp_path / "project"
    project.mkdir()
    
    # Ar file with violation
    ar_file = project / "ar.json"
    ar_file.write_text(json.dumps({"welcome": "يا زبون"}, ensure_ascii=False), encoding="utf-8")
    
    # En file
    en_file = project / "en.json"
    en_file.write_text(json.dumps({"welcome": "Welcome"}, ensure_ascii=False), encoding="utf-8")
    
    # Glossary
    glossary_data = {
        "terms": [{"forbidden_ar": ["زبون"], "approved_ar": "عميل"}]
    }
    
    # Toolkit config
    ws = project / ".l10n-audit"
    ws.mkdir()
    config_dir = ws / "config"
    config_dir.mkdir()
    
    # Create project_profiles.json
    profiles_file = config_dir / "project_profiles.json"
    profiles_file.write_text(json.dumps({
        "profiles": {
            "json_flat": {
                "name": "json_flat",
                "description": "JSON Flat Profile",
                "locale_format": "json",
                "source_locale": "en",
                "target_locales": ["ar"],
                "project_markers": [[]] # Root marker
            }
        }
    }), encoding="utf-8")
    
    # Putting glossary in the tools_dir (.l10n-audit)
    glossary_file = ws / "glossary.json"
    glossary_file.write_text(json.dumps(glossary_data, ensure_ascii=False), encoding="utf-8")
    
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({
        "project_profile": "json_flat",
        "source_locale": "en",
        "target_locales": ["ar"],
        "en_file": str(en_file),
        "ar_file": str(ar_file),
        "glossary_file": "glossary.json" # Relative to .l10n-audit
    }), encoding="utf-8")
    
    # We also need a dummy cli.py for load_runtime to work
    (ws / "cli.py").write_text("# dummy")
    (project / "lib").mkdir(parents=True, exist_ok=True)

    # Run audit with apply_safe_fixes=True
    # We use stage='terminology' to be fast
    result = run_audit(project, stage="terminology", apply_safe_fixes=True)
    
    assert result.success
    
    # Check if ar.json was fixed
    fixed_ar = json.loads(ar_file.read_text(encoding="utf-8"))
    assert fixed_ar["welcome"] == "يا عميل"
