import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.core.cli import (
    build_parser,
    cmd_generate_adaptation_report,
)
from l10n_audit.core.adaptation_intelligence import load_adaptation_report


def _learning_profile_payload() -> dict:
    return {
        "project_id": "test_project",
        "run_count": 10,
        "avg_total_issues": 15.0,
        "avg_auto_fix_rate": 0.05,
        "avg_ai_review_rate": 0.90,
        "avg_manual_review_rate": 0.75,
        "avg_context_adjusted_rate": 0.50,
        "dominant_category": "grammar",
        "arabic_run_count": 9,
        "calibration_active_runs": 1,
        "routing_enabled_runs": 5,
        "first_seen": 1000.0,
        "last_seen": 9000.0,
    }


def test_generate_adaptation_report_subcommand_wiring():
    parser = build_parser()
    args = parser.parse_args(
        ["generate-adaptation-report", "--learning-profile", "learning.json", "--mode", "suggest"]
    )

    assert args.command == "generate-adaptation-report"
    assert args.func is cmd_generate_adaptation_report
    assert args.learning_profile == "learning.json"
    assert args.mode == "suggest"


def test_cmd_generate_adaptation_report_success(tmp_path):
    learning_profile = tmp_path / "learning_profile.json"
    learning_profile.write_text(json.dumps(_learning_profile_payload()), encoding="utf-8")
    out_report = tmp_path / "adaptation_report.json"

    args = argparse.Namespace(
        path=".",
        learning_profile=str(learning_profile),
        out_report=str(out_report),
        mode="prepare_bounded_actions",
    )

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")):
        assert cmd_generate_adaptation_report(args) == 0

    assert out_report.exists()
    report = load_adaptation_report(str(out_report))
    assert report.mode == "prepare_bounded_actions"
    assert report.project_id == "test_project"
    assert any(p.bounded_action_key for p in report.proposals if p.proposal_type == "bounded_action_candidate")


def test_cmd_generate_adaptation_report_invalid_input_fails(tmp_path, capsys):
    bad_profile = tmp_path / "bad_learning.json"
    bad_profile.write_text(json.dumps({"project_id": "x"}), encoding="utf-8")
    args = argparse.Namespace(
        path=".",
        learning_profile=str(bad_profile),
        out_report=str(tmp_path / "adaptation_report.json"),
        mode="suggest",
    )

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")):
        assert cmd_generate_adaptation_report(args) == 1

    assert "ERROR:" in capsys.readouterr().err


def test_generate_adaptation_report_not_wired_into_run():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    help_text = run_parser.format_help()

    assert "generate-adaptation-report" not in help_text


def test_generate_adaptation_report_output_bridges_to_manifest_workflow(tmp_path):
    learning_profile = tmp_path / "learning_profile.json"
    learning_profile.write_text(json.dumps(_learning_profile_payload()), encoding="utf-8")
    adaptation_report = tmp_path / "adaptation_report.json"

    adapt_args = argparse.Namespace(
        path=".",
        learning_profile=str(learning_profile),
        out_report=str(adaptation_report),
        mode="prepare_bounded_actions",
    )
    manifest_args = argparse.Namespace(
        path=".",
        input_report=str(adaptation_report),
        manifest_out=str(tmp_path / "manifest.json"),
        mode="review_ready",
    )
    manifest = MagicMock()
    manifest.project_id = "test_project"
    manifest.manifest_id = "mfst123"
    manifest.generated_actions = []
    manifest.rejected_candidates = []

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.cli.workspace_config_path", return_value=tmp_path / "config.json"), \
         patch("l10n_audit.core.controlled_consumption.generate_consumption_manifest", return_value=manifest) as mock_generate, \
         patch("l10n_audit.core.controlled_consumption.write_manifest_file") as mock_write:
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")
        assert cmd_generate_adaptation_report(adapt_args) == 0

        from l10n_audit.core.cli import cmd_generate_manifest

        assert cmd_generate_manifest(manifest_args) == 0
        loaded_report = mock_generate.call_args.args[0]
        assert loaded_report.project_id == "test_project"
        assert loaded_report.mode == "prepare_bounded_actions"
        mock_write.assert_called_once_with(manifest, str(tmp_path / "manifest.json"))
