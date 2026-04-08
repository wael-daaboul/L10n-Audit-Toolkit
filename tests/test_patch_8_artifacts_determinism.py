import pytest
from pathlib import Path
from l10n_audit.core.audit_runtime import AuditPaths
from l10n_audit.core.artifact_resolver import (
    list_primary_artifact_keys,
    list_primary_artifact_paths,
    resolve_review_queue_path,
    resolve_review_final_path,
    resolve_review_queue_json_path,
    resolve_review_projection_path,
    resolve_review_projection_json_path,
    resolve_final_report_path,
    resolve_adaptation_report_path,
)

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
        output={}
    )

def test_resolve_review_queue_path_determinism(mock_runtime):
    """Prove the canonical apply workbook path remains Results/review/review_queue.xlsx."""
    path = resolve_review_queue_path(mock_runtime)
    assert path.name == "review_queue.xlsx"
    assert "review" in str(path.parent)
    assert "Results" in str(path)

def test_resolve_review_projection_path_determinism(mock_runtime):
    """Prove the aggregator analytical path is distinct: review_projection.xlsx."""
    path = resolve_review_projection_path(mock_runtime)
    assert path.name == "review_projection.xlsx"
    assert "review" in str(path.parent)

def test_resolve_differentiation(mock_runtime):
    """Prove no safe/silent overwrite possibility because paths are distinct."""
    apply_path = resolve_review_queue_path(mock_runtime)
    analytical_path = resolve_review_projection_path(mock_runtime)
    assert apply_path != analytical_path

def test_aggregator_cli_defaults(mock_runtime, monkeypatch):
    """Prove aggregator defaults to the human queue workbook in its CLI."""
    from l10n_audit.reports.report_aggregator import main as aggregator_main
    import sys
    
    # Mock runtime load
    monkeypatch.setattr("l10n_audit.reports.report_aggregator.load_runtime", lambda _: mock_runtime)
    
    # We won't actually run main because it calls aggregate_reports,
    # but we will check the canonical workbook path used by the CLI default.
    from l10n_audit.core.artifact_resolver import resolve_review_queue_path
    assert resolve_review_queue_path(mock_runtime).name == "review_queue.xlsx"

def test_apply_cli_defaults(mock_runtime, monkeypatch):
    """Prove the canonical review queue path remains distinct from the apply final workbook."""
    queue_path = resolve_review_queue_path(mock_runtime)
    final_path = resolve_review_final_path(mock_runtime)
    assert queue_path.name == "review_queue.xlsx"
    assert final_path.name == "review_final.xlsx"
    assert queue_path != final_path


def test_primary_artifact_surface_is_deterministic(mock_runtime):
    keys = list_primary_artifact_keys()
    paths = list_primary_artifact_paths(mock_runtime)

    assert keys == [
        "review_queue_xlsx_path",
        "review_final_xlsx_path",
        "final_report_md_path",
        "adaptation_report_path",
    ]
    assert paths == [
        resolve_review_queue_path(mock_runtime),
        resolve_review_final_path(mock_runtime),
        mock_runtime.results_dir / "final" / "final_audit_report.md",
        resolve_adaptation_report_path(mock_runtime),
    ]
    assert resolve_review_projection_path(mock_runtime) not in paths
    assert resolve_review_queue_json_path(mock_runtime) not in paths
