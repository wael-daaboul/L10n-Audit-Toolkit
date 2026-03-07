from pathlib import Path

from conftest import load_json, validate_schema


def test_valid_glossary_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "glossary" / "valid_glossary.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "glossary.schema.json")
    assert errors == []


def test_invalid_glossary_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "glossary" / "invalid_glossary.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "glossary.schema.json")
    assert errors
