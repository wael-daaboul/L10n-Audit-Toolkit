import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from l10n_audit.core.cli import (
    build_parser,
    cmd_apply_manifest,
    cmd_generate_manifest,
    cmd_review_manifest,
)


def test_generate_manifest_subcommand_wiring():
    parser = build_parser()
    args = parser.parse_args(["generate-manifest", "--input-report", "adaptation.json"])

    assert args.command == "generate-manifest"
    assert args.func is cmd_generate_manifest
    assert args.path == "."
    assert args.input_report == "adaptation.json"
    assert args.mode == "review_ready"


def test_review_manifest_subcommand_wiring():
    parser = build_parser()
    args = parser.parse_args(
        ["review-manifest", "--manifest", "manifest.json", "--approvals", "approvals.json"]
    )

    assert args.command == "review-manifest"
    assert args.func is cmd_review_manifest
    assert args.manifest == "manifest.json"
    assert args.approvals == "approvals.json"
    assert args.reviewed_out is None


def test_apply_manifest_subcommand_wiring():
    parser = build_parser()
    args = parser.parse_args(
        ["apply-manifest", "--manifest", "manifest.json", "--reviewed-manifest", "reviewed.json"]
    )

    assert args.command == "apply-manifest"
    assert args.func is cmd_apply_manifest
    assert args.config is None


def test_cmd_generate_manifest_success(tmp_path):
    args = argparse.Namespace(
        path=".",
        input_report="adaptation.json",
        manifest_out=str(tmp_path / "manifest.json"),
        mode="review_ready",
    )
    manifest = MagicMock()
    manifest.project_id = "proj"
    manifest.manifest_id = "abc123"
    manifest.generated_actions = [object()]
    manifest.rejected_candidates = []

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.cli.workspace_config_path", return_value=tmp_path / "config.json"), \
         patch("l10n_audit.core.adaptation_intelligence.load_adaptation_report", return_value=object()), \
         patch("l10n_audit.core.controlled_consumption.generate_consumption_manifest", return_value=manifest) as mock_generate, \
         patch("l10n_audit.core.controlled_consumption.write_manifest_file") as mock_write:
        (tmp_path / "config.json").write_text("{}", encoding="utf-8")

        assert cmd_generate_manifest(args) == 0
        mock_generate.assert_called_once()
        mock_write.assert_called_once_with(manifest, str(tmp_path / "manifest.json"))


def test_cmd_review_manifest_success(tmp_path):
    args = argparse.Namespace(
        path=".",
        manifest="manifest.json",
        approvals="approvals.json",
        reviewed_out=str(tmp_path / "reviewed.json"),
    )
    reviewed = MagicMock()
    reviewed.project_id = "proj"
    reviewed.reviewed_manifest_id = "rev123"
    reviewed.approved_actions = [object()]

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.manifest_application.load_approvals_file", return_value={"a": {"status": "approved"}}), \
         patch("l10n_audit.core.manifest_application.generate_reviewed_manifest", return_value=reviewed) as mock_review:
        assert cmd_review_manifest(args) == 0
        mock_review.assert_called_once_with(
            "manifest.json",
            {"a": {"status": "approved"}},
            ".l10n-audit/Results",
            out_path=str(tmp_path / "reviewed.json"),
        )


def test_cmd_apply_manifest_success():
    args = argparse.Namespace(
        path=".",
        manifest="manifest.json",
        reviewed_manifest="reviewed.json",
        config=None,
    )
    receipt = MagicMock()
    receipt.source_reviewed_manifest_id = "rev123"
    receipt.applied_actions = ["a1"]
    receipt.skipped_actions = ["a2"]
    receipt.failed_actions = []

    with patch("l10n_audit.core.cli.find_project_root", return_value=Path(".")), \
         patch("l10n_audit.core.cli.workspace_config_path", return_value=Path("config.json")), \
        patch("l10n_audit.core.manifest_application.apply_manifest", return_value=receipt) as mock_apply:
        assert cmd_apply_manifest(args) == 0
        mock_apply.assert_called_once_with(
            "reviewed.json",
            "manifest.json",
            "config.json",
            ".l10n-audit/Results",
        )


def test_manifest_workflow_not_wired_into_run():
    parser = build_parser()
    run_parser = parser._subparsers._group_actions[0].choices["run"]
    help_text = run_parser.format_help()

    assert "generate-manifest" not in help_text
    assert "review-manifest" not in help_text
    assert "apply-manifest" not in help_text
