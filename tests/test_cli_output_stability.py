from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from l10n_audit.core.audit_report_utils import write_unified_json
from l10n_audit.core.cli import _format_duration, cmd_run


def _run_args(path: Path, *, verbose: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=None,
        path=str(path),
        stage="fast",
        verbose=verbose,
        force=False,
        reset=False,
        ai_enabled=False,
        ai_api_key=None,
        ai_api_base=None,
        ai_model=None,
        apply_safe_fixes=False,
        retention_mode=None,
        retention_prefix=None,
        translate_missing=False,
        glossary=None,
        out_xlsx=None,
        schema=None,
        input_report=None,
    )


def _fake_success_result() -> SimpleNamespace:
    return SimpleNamespace(
        success=True,
        error_message="",
        summary=SimpleNamespace(
            total_issues=3,
            missing_keys=1,
            unused_keys=0,
            empty_translations=0,
            placeholder_errors=1,
            terminology_errors=0,
            ar_qc_issues=1,
        ),
        reports=[SimpleNamespace(path="/tmp/report.json")],
        duration_ms=65432,
        metadata={
            "ai_review_status": {"status": "degraded", "degraded": True},
            "report_export_status": {
                "status": "partial_failure",
                "failed_exports": ["Final Report (JSON): Object of type set is not JSON serializable"],
            },
        },
    )


def test_write_unified_json_normalizes_sets_to_sorted_lists(tmp_path: Path) -> None:
    out = tmp_path / "payload.json"
    write_unified_json(
        out,
        {
            "sources": {"b", "a"},
            "nested": {"items": {3, 1, 2}},
        },
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sources"] == ["a", "b"]
    assert data["nested"]["items"] == [1, 2, 3]


def test_cmd_run_summary_surfaces_export_failure_and_ai_degradation(tmp_path: Path, capsys) -> None:
    fake_root = ModuleType("l10n_audit")
    fake_root.__version__ = "1.7.0"
    fake_root.run_audit = lambda *args, **kwargs: _fake_success_result()
    fake_api = ModuleType("l10n_audit.api")
    fake_api._stage_module_names = lambda *args, **kwargs: ["audits.l10n_audit_pro"]

    args = _run_args(tmp_path)
    cfg = tmp_path / ".l10n-audit" / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("{}", encoding="utf-8")

    with patch.dict(sys.modules, {"l10n_audit": fake_root, "l10n_audit.api": fake_api}):
        with patch("l10n_audit.core.cli.find_project_root", return_value=tmp_path), patch(
            "l10n_audit.core.cli.workspace_config_path", return_value=cfg
        ):
            assert cmd_run(args) == 0

    output = capsys.readouterr().out
    assert "Audit completed with warnings" in output
    assert "AI review        : degraded" in output
    assert "Report export    : partial failure" in output
    assert "Object of type set is not JSON serializable" in output
    assert "Duration         : 1m 5.4s" in output


def test_format_duration_is_human_readable() -> None:
    assert _format_duration(250) == "250 ms"
    assert _format_duration(1500) == "1.5s"
    assert _format_duration(65000) == "1m 5.0s"
