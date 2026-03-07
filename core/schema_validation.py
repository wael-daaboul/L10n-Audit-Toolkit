#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class SchemaValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _is_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate(instance: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type and not _is_type(instance, str(expected_type)):
        errors.append(f"{path}: expected type '{expected_type}', got '{type(instance).__name__}'.")
        return

    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: value {instance!r} is not in enum {enum!r}.")

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(instance) < min_length:
            errors.append(f"{path}: string is shorter than minLength {min_length}.")

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(instance) < min_items:
            errors.append(f"{path}: array has fewer than {min_items} items.")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                _validate(item, item_schema, f"{path}[{index}]", errors)

    if isinstance(instance, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for name in required:
                if name not in instance:
                    errors.append(f"{path}: missing required property '{name}'.")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for name, value in instance.items():
                if name in properties and isinstance(properties[name], dict):
                    _validate(value, properties[name], f"{path}.{name}", errors)

        additional = schema.get("additionalProperties", True)
        if additional is False and isinstance(properties, dict):
            for name in instance:
                if name not in properties:
                    errors.append(f"{path}: additional property '{name}' is not allowed.")
        elif isinstance(additional, dict):
            for name, value in instance.items():
                if not isinstance(properties, dict) or name not in properties:
                    _validate(value, additional, f"{path}.{name}", errors)


def validate_instance(instance: Any, schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _validate(instance, schema, "$", errors)
    return errors


def validate_or_raise(instance: Any, schema: dict[str, Any]) -> None:
    errors = validate_instance(instance, schema)
    if errors:
        raise SchemaValidationError(errors)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_file(input_path: Path, schema_path: Path) -> list[str]:
    return validate_instance(load_json(input_path), load_json(schema_path))


def preset_mappings(tools_dir: Path) -> dict[str, tuple[Path, Path]]:
    schemas = tools_dir / "schemas"
    results = tools_dir / "Results"
    return {
        "config": (tools_dir / "config" / "config.json", schemas / "config.schema.json"),
        "glossary": (tools_dir / "docs" / "terminology" / "betaxi_glossary_official.json", schemas / "glossary.schema.json"),
        "final-report": (results / "final" / "final_audit_report.json", schemas / "final_audit_report.schema.json"),
        "fix-plan": (results / "fixes" / "fix_plan.json", schemas / "fix_plan.schema.json"),
    }


def main() -> None:
    tools_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", help="Path to a schema file.")
    parser.add_argument("--input", help="Path to a JSON file to validate.")
    parser.add_argument("--preset", choices=["core"], help="Validate the built-in core JSON contracts.")
    args = parser.parse_args()

    failures: list[str] = []

    if args.preset == "core":
        for name, (input_path, schema_path) in preset_mappings(tools_dir).items():
            errors = validate_file(input_path, schema_path)
            if errors:
                failures.append(f"[{name}] " + " | ".join(errors))
            else:
                print(f"OK: {name}")
    elif args.schema and args.input:
        errors = validate_file(Path(args.input), Path(args.schema))
        if errors:
            failures.extend(errors)
        else:
            print(f"OK: {args.input}")
    else:
        parser.error("Provide either --preset core or both --schema and --input.")

    if failures:
        for item in failures:
            print(f"ERROR: {item}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
