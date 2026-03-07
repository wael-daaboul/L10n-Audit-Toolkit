from pathlib import Path

from core.schema_validation import validate_file


def test_schema_validation_cli_helper(tools_dir: Path) -> None:
    errors = validate_file(
        tools_dir / "config" / "config.json",
        tools_dir / "schemas" / "config.schema.json",
    )
    assert errors == []
