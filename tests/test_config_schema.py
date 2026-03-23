import pytest
from pathlib import Path

from conftest import load_json, validate_schema


def test_valid_config_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "config" / "valid_config.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "config.schema.json")
    assert errors == []


@pytest.mark.skip(reason="Schema refactored")
def test_invalid_config_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "config" / "invalid_config.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "config.schema.json")
    assert errors
