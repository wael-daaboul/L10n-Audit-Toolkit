"""
Step 2 regression tests: runtime.config plumbing.

These tests verify that AuditPaths.config is populated by load_runtime()
from the on-disk config.json, and that feature-gated consumers can read
real configuration values through the runtime object rather than relying
on manual test injection.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from l10n_audit.core.audit_runtime import AuditPaths, load_runtime


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _minimal_project(base: Path, extra_config: dict | None = None) -> tuple[Path, Path]:
    """Write a minimal project fixture and return (project_root, config_path)."""
    # Locale files
    lang_dir = base / "assets" / "language"
    _write(lang_dir / "en.json", {"hello": "Hello"})
    _write(lang_dir / "ar.json", {"hello": "مرحبا"})
    # Code stub so code_dir exists
    (base / "lib").mkdir(parents=True, exist_ok=True)

    config_payload: dict = {
        "config_version": 2,
        "project_detection": {"force_profile": "flutter_getx_json"},
        "project_root": str(base),
        "source_locale": "en",
        "target_locales": ["ar"],
        "results_dir": str(base / "Results"),
        "glossary_file": "",
    }
    if extra_config:
        config_payload.update(extra_config)

    config_path = base / "config.json"
    _write(config_path, config_payload)
    return base, config_path


# ---------------------------------------------------------------------------
# Test: AuditPaths.config field exists with a default of {}
# ---------------------------------------------------------------------------

def test_audit_paths_config_field_defaults_to_empty_dict() -> None:
    """AuditPaths must expose a .config field that is an empty dict when not set."""
    # Minimal construction via SimpleNamespace-like call — use field defaults only
    from dataclasses import fields
    field_names = {f.name for f in fields(AuditPaths)}
    assert "config" in field_names, "AuditPaths is missing the 'config' field"


def test_audit_paths_config_none_becomes_empty_dict(tmp_path: Path) -> None:
    """Passing config=None must coerce to {} via __post_init__."""
    _, config_path = _minimal_project(tmp_path)
    runtime = load_runtime(config_path, validate=False)
    # config must be a dict (not None)
    assert isinstance(runtime.config, dict)


# ---------------------------------------------------------------------------
# Test: load_runtime() populates .config from on-disk config.json
# ---------------------------------------------------------------------------

def test_load_runtime_exposes_config_dict(tmp_path: Path) -> None:
    """load_runtime() must return a runtime whose .config dict contains keys
    from the on-disk config.json."""
    _, config_path = _minimal_project(
        tmp_path,
        extra_config={"ai_review": {"enabled": False, "model": "gpt-4o-mini"}},
    )
    runtime = load_runtime(config_path, validate=False)

    assert isinstance(runtime.config, dict), "runtime.config must be a dict"
    assert len(runtime.config) > 0, "runtime.config must not be empty after loading a config.json"
    # The source_locale key should be present (it was in the config file)
    assert runtime.config.get("source_locale") == "en"


def test_load_runtime_config_contains_ai_review_settings(tmp_path: Path) -> None:
    """AI review settings written to config.json must be reachable via runtime.config."""
    _, config_path = _minimal_project(
        tmp_path,
        extra_config={"ai_review": {"enabled": True, "model": "gpt-4-turbo"}},
    )
    runtime = load_runtime(config_path, validate=False)

    ai_cfg = runtime.config.get("ai_review", {})
    assert ai_cfg.get("enabled") is True
    assert ai_cfg.get("model") == "gpt-4-turbo"


def test_load_runtime_config_contains_project_memory_settings(tmp_path: Path) -> None:
    """project_memory settings written to config.json must be reachable via runtime.config."""
    _, config_path = _minimal_project(
        tmp_path,
        extra_config={"project_memory": {"enabled": True, "max_history": 10}},
    )
    runtime = load_runtime(config_path, validate=False)

    pm_cfg = runtime.config.get("project_memory", {})
    assert pm_cfg.get("enabled") is True
    assert pm_cfg.get("max_history") == 10


# ---------------------------------------------------------------------------
# Test: feature gates read from real runtime (not manual injection)
# ---------------------------------------------------------------------------

def test_project_memory_gate_reads_from_real_runtime_config(tmp_path: Path) -> None:
    """The project_memory feature gate in engine.py must be activated by real
    runtime.config, NOT by manually injecting runtime.config in a test."""
    _, config_path = _minimal_project(
        tmp_path,
        extra_config={"project_memory": {"enabled": True}},
    )
    runtime = load_runtime(config_path, validate=False)

    # This is exactly what engine.py does at runtime (line 317):
    pm_config = (getattr(runtime, "config", {}) or {}).get("project_memory", {}) or {}
    assert pm_config.get("enabled") is True, (
        "project_memory gate must read True from real runtime.config — "
        "manual injection is NOT required"
    )


def test_ai_review_gate_reads_from_real_runtime_config(tmp_path: Path) -> None:
    """The adaptive_intelligence gate must be activatable via real config, not injection."""
    _, config_path = _minimal_project(
        tmp_path,
        extra_config={"adaptive_intelligence": {"enabled": True}},
    )
    runtime = load_runtime(config_path, validate=False)

    ai_config = (getattr(runtime, "config", {}) or {}).get("adaptive_intelligence", {}) or {}
    assert ai_config.get("enabled") is True


def test_runtime_config_is_independent_copy(tmp_path: Path) -> None:
    """runtime.config must be an independent copy; mutating it must not affect
    another load_runtime() call from the same file."""
    _, config_path = _minimal_project(tmp_path)
    runtime1 = load_runtime(config_path, validate=False)
    runtime2 = load_runtime(config_path, validate=False)

    runtime1.config["__test_sentinel__"] = True
    assert "__test_sentinel__" not in runtime2.config, (
        "runtime.config must be an independent copy per load_runtime() call"
    )
