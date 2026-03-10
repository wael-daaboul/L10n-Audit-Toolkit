from pathlib import Path

from core.audit_runtime import _discover_glossary_path
from core.schema_validation import preset_mappings


def test_runtime_prefers_neutral_glossary_filename(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    terminology_dir = docs_dir / "terminology"
    terminology_dir.mkdir(parents=True)
    (terminology_dir / "glossary.json").write_text("{}", encoding="utf-8")
    (terminology_dir / "z_project_terms.json").write_text("{}", encoding="utf-8")

    discovered = _discover_glossary_path(docs_dir)

    assert discovered == (terminology_dir / "glossary.json").resolve()


def test_schema_validation_preset_uses_first_available_glossary_json(tmp_path: Path) -> None:
    tools_dir = tmp_path
    (tools_dir / "schemas").mkdir()
    (tools_dir / "Results" / "final").mkdir(parents=True)
    (tools_dir / "Results" / "fixes").mkdir(parents=True)
    terminology_dir = tools_dir / "docs" / "terminology"
    terminology_dir.mkdir(parents=True)
    (terminology_dir / "custom_terms.json").write_text("{}", encoding="utf-8")

    mappings = preset_mappings(tools_dir)

    assert mappings["glossary"][0] == terminology_dir / "custom_terms.json"
