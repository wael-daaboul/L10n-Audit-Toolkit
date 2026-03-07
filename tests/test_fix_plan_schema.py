from pathlib import Path

from conftest import load_json, validate_schema


def test_fixture_fix_plan_matches_schema(fixtures_dir: Path, tools_dir: Path) -> None:
    payload = load_json(fixtures_dir / "reports" / "fix_plan.valid.json")
    errors = validate_schema(payload, tools_dir / "schemas" / "fix_plan.schema.json")
    assert errors == []


def test_invalid_fix_plan_fails_schema(tools_dir: Path) -> None:
    payload = {
        "summary": {"total_plan_items": 1, "auto_safe": 0, "review_required": 1, "applied_to_candidates": 0, "by_source": {}},
        "plan": [{"key": "x", "classification": "unsafe"}],
    }
    errors = validate_schema(payload, tools_dir / "schemas" / "fix_plan.schema.json")
    assert errors
