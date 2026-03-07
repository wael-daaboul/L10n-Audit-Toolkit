from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.schema_validation import validate_instance


TOOLS_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = TOOLS_DIR / "tests" / "fixtures"
RUNTIME_TEST_CONFIG = FIXTURES_DIR / "config" / "config.json"


@pytest.fixture()
def tools_dir() -> Path:
    return TOOLS_DIR


@pytest.fixture()
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture()
def runtime_test_config() -> Path:
    return RUNTIME_TEST_CONFIG


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_schema(instance, schema_path: Path) -> list[str]:
    schema = load_json(schema_path)
    return validate_instance(instance, schema)


def run_module(module: str, args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("L10N_AUDIT_CONFIG", str(RUNTIME_TEST_CONFIG))
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(cwd or TOOLS_DIR),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
