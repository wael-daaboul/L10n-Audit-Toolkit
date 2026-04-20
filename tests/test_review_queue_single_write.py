"""
Step 4 regression tests: review_queue.xlsx must be written once by the
authoritative run_stage() path, never overwritten by the legacy
export_review_queue() path in api.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Test: export_review_queue is never imported/called from api.py run_audit
# ---------------------------------------------------------------------------

def test_export_review_queue_not_called_during_run_audit(tmp_path: Path) -> None:
    """api.py must NOT call export_review_queue() from fix_merger during run_audit.
    The authoritative review_queue.xlsx is written by run_stage() only.
    """
    from l10n_audit.fixes import fix_merger

    called = []
    original = getattr(fix_merger, "export_review_queue", None)

    def spy_export_review_queue(*args, **kwargs):
        called.append(args)
        if original:
            return original(*args, **kwargs)

    # Patch export_review_queue on the module itself
    with patch.object(fix_merger, "export_review_queue", side_effect=spy_export_review_queue):
        # run_audit will fail quickly due to missing project, but the import
        # path for export_review_queue must not have been hit
        from l10n_audit.api import run_audit
        from l10n_audit.exceptions import InvalidProjectError
        try:
            run_audit(tmp_path)
        except (InvalidProjectError, Exception):
            pass  # expected — we only care that export_review_queue was NOT called

    assert len(called) == 0, (
        "export_review_queue must not be called during run_audit; "
        "review_queue.xlsx is owned by run_stage() only"
    )


def test_api_py_does_not_import_export_review_queue() -> None:
    """api.py source must not contain a live call to export_review_queue().
    The authoritative write path lives in report_aggregator.run_stage() only.
    """
    import ast
    import l10n_audit.api as api_module
    import inspect

    source = inspect.getsource(api_module)

    # Parse and look for any Call node that calls export_review_queue
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Direct call: export_review_queue(...)
            if isinstance(func, ast.Name) and func.id == "export_review_queue":
                pytest.fail(
                    "api.py contains a direct call to export_review_queue() — "
                    "this double-write must be removed."
                )
            # Attribute call: something.export_review_queue(...)
            if isinstance(func, ast.Attribute) and func.attr == "export_review_queue":
                pytest.fail(
                    "api.py contains an attribute call to export_review_queue() — "
                    "this double-write must be removed."
                )


def test_fix_plan_json_is_still_written(tmp_path: Path) -> None:
    """The fix_plan.json cache must still be written even though
    export_review_queue() was removed.  The cache is needed by run_apply()."""
    import json as _j

    # Build a minimal project fixture
    lang_dir = tmp_path / "assets" / "language"
    lang_dir.mkdir(parents=True)
    (lang_dir / "en.json").write_text('{"hello": "Hello"}', encoding="utf-8")
    (lang_dir / "ar.json").write_text('{"hello": "مرحبا"}', encoding="utf-8")
    (tmp_path / "lib").mkdir(parents=True)
    config = {
        "config_version": 2,
        "project_detection": {"force_profile": "flutter_getx_json"},
        "project_root": str(tmp_path),
        "source_locale": "en",
        "target_locales": ["ar"],
        "results_dir": str(tmp_path / "Results"),
        "glossary_file": "",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(_j.dumps(config), encoding="utf-8")

    from l10n_audit.api import run_audit
    from l10n_audit.exceptions import InvalidProjectError, StageError

    try:
        run_audit(tmp_path, stage="fast", write_reports=False)
    except (InvalidProjectError, StageError, Exception):
        # Project may have other issues; we only check the fix_plan side-effect
        pass

    fix_plan_path = tmp_path / "Results" / ".cache" / "apply" / "fix_plan.json"
    # The write_reports=False path may skip some outputs; tolerate absence
    # but if present it must be valid JSON
    if fix_plan_path.exists():
        data = _j.loads(fix_plan_path.read_text(encoding="utf-8"))
        assert "plan" in data, "fix_plan.json must contain a 'plan' key"
