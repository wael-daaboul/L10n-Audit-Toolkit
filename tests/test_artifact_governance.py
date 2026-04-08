from pathlib import Path

import pytest

from l10n_audit.core.audit_runtime import AuditPaths
from l10n_audit.core.artifact_resolver import (
    get_registry_name_for_artifact_key,
    list_primary_artifact_paths,
)
from l10n_audit.core.deprecation_registry import (
    get_by_name,
    get_governance_classification,
    summary_dict,
    validate_governance_registry,
)
from l10n_audit.core.deprecation_warnings import warn_deprecated_artifact


@pytest.fixture
def mock_runtime(tmp_path):
    results = tmp_path / "Results"
    results.mkdir()
    return AuditPaths(
        tools_dir=tmp_path,
        config_dir=tmp_path / "config",
        docs_dir=tmp_path / "docs",
        vendor_dir=tmp_path / "vendor",
        project_root=tmp_path / "project",
        locales_dir=tmp_path / "locales",
        en_file=tmp_path / "locales" / "en.json",
        ar_file=tmp_path / "locales" / "ar.json",
        code_dir=tmp_path / "lib",
        code_dirs=(tmp_path / "lib",),
        glossary_file=tmp_path / "glossary.json",
        results_dir=results,
        languagetool_dir=tmp_path / "lt",
        languagetool_configured_dir=None,
        project_profile="flutter_arb",
        locale_format="json",
        locale_root=tmp_path / "locales",
        source_locale="en",
        target_locales=("ar",),
        locale_paths={},
        usage_patterns=(),
        usage_wrappers=(),
        usage_accessors=(),
        usage_config_fields=(),
        allowed_extensions=(),
        profile_notes="",
        profile_selection_mode="auto",
        profile_score=100,
        profile_reasons=(),
        role_identifiers=(),
        entity_whitelist={},
        latin_whitelist=(),
        ai_review={},
        output={},
    )


def test_registry_governance_coverage_for_converged_artifacts():
    required = {
        "review_queue_xlsx": "primary_workflow",
        "review_final_xlsx": "primary_workflow",
        "final_audit_report_md": "primary_workflow",
        "adaptation_report_json": "primary_workflow",
        "consumption_manifest_json": "primary_workflow",
        "reviewed_manifest_json": "primary_workflow",
        "manifest_receipt_json": "primary_workflow",
        "apply_rejection_report_json": "internal_only",
        "review_queue_json": "compatibility_only",
        "aggregated_issues_json": "compatibility_only",
        "fix_plan_xlsx": "compatibility_only",
        "final_locale_ar_final_json": "compatibility_only",
        "review_projection_xlsx": "deprecated_candidate",
    }

    assert validate_governance_registry() == []
    for artifact_name, governance in required.items():
        entry = get_by_name(artifact_name)
        assert entry is not None, artifact_name
        assert get_governance_classification(artifact_name) == governance


def test_adaptation_and_manifest_roles_are_explicit():
    assert get_governance_classification("adaptation_report_json") == "primary_workflow"
    assert get_governance_classification("consumption_manifest_json") == "primary_workflow"
    assert get_governance_classification("reviewed_manifest_json") == "primary_workflow"
    assert get_governance_classification("manifest_receipt_json") == "primary_workflow"
    assert get_governance_classification("manifest_rollback_records") == "internal_only"
    assert get_governance_classification("apply_rejection_report_json") == "internal_only"


def test_primary_surface_excludes_compatibility_and_deprecated(mock_runtime):
    surface = [path.as_posix() for path in list_primary_artifact_paths(mock_runtime)]

    assert surface == [
        (mock_runtime.results_dir / "review" / "review_queue.xlsx").as_posix(),
        (mock_runtime.results_dir / "review" / "review_final.xlsx").as_posix(),
        (mock_runtime.results_dir / "final" / "final_audit_report.md").as_posix(),
        (mock_runtime.results_dir / ".cache" / "adaptation" / "adaptation_report.json").as_posix(),
    ]
    assert all("review_projection.xlsx" not in path for path in surface)
    assert all("review_queue.json" not in path for path in surface)


def test_warning_consistency_matches_governance(caplog):
    with caplog.at_level("DEBUG"):
        warn_deprecated_artifact("review_queue_json", Path("Results/review/review_queue.json"), "read")
    assert "Governance: compatibility_only" in caplog.text

    with pytest.raises(RuntimeError, match="Strict Mode Violation"):
        warn_deprecated_artifact(
            "review_projection_xlsx",
            Path("Results/review/review_projection.xlsx"),
            "read",
            strict_mode=True,
        )


def test_no_alias_drift_between_registry_and_resolver():
    expected = {
        "review_queue_xlsx_path": "review_queue_xlsx",
        "review_final_xlsx_path": "review_final_xlsx",
        "review_projection_xlsx_path": "review_projection_xlsx",
        "review_queue_json_path": "review_queue_json",
        "review_machine_queue_json_path": "review_machine_queue_json",
        "adaptation_report_path": "adaptation_report_json",
    }
    assert {key: get_registry_name_for_artifact_key(key) for key in expected} == expected


def test_summary_exposes_governance_buckets():
    summary = summary_dict()

    assert summary["governance_validation_errors"] == []
    assert "review_queue_xlsx" in summary["by_governance_classification"]["primary_workflow"]
    assert "apply_rejection_report_json" in summary["by_governance_classification"]["internal_only"]
    assert "review_queue_json" in summary["by_governance_classification"]["compatibility_only"]
    assert "review_projection_xlsx" in summary["by_governance_classification"]["deprecated_candidate"]
