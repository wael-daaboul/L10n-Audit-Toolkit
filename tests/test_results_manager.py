from l10n_audit.models import AuditOptions, OutputOptions
from l10n_audit.core.results_manager import manage_previous_results

def test_manage_previous_results_overwrite(tmp_path):
    results_dir = tmp_path / "Results"
    results_dir.mkdir()
    
    # Active files
    (results_dir / "final_report.md").write_text("old report")
    (results_dir / "per_tool").mkdir()
    (results_dir / "per_tool" / "tool.json").write_text("{}")
    
    # Archive folders (should be preserved)
    (results_dir / "audit_v1").mkdir()
    
    options = AuditOptions(output=OutputOptions(retention_mode="overwrite"))
    manage_previous_results(results_dir, options)
    
    assert (results_dir / "audit_v1").exists()
    assert not (results_dir / "final_report.md").exists()
    assert not (results_dir / "per_tool").exists()

def test_manage_previous_results_archive(tmp_path):
    results_dir = tmp_path / "Results"
    results_dir.mkdir()
    
    # Active files
    (results_dir / "final_report.md").write_text("old content")
    (results_dir / "per_tool").mkdir()
    (results_dir / "per_tool" / "tool.json").write_text("{}")
    
    # Existing archives
    (results_dir / "audit_v1").mkdir()
    
    options = AuditOptions(output=OutputOptions(retention_mode="archive"))
    manage_previous_results(results_dir, options)
    
    # Check v2 archive (expected for next)
    # The current manage_previous_results logic might name it project_v1 if it's the first archive matching prefix
    # But previous tests expected audit_v2 if v1 existed.
    # Let's check results_manager.py logic if it uses prefix.
    # If prefix is "audit", and audit_v1 exists, it should find audit_v2.
    v2_archive = results_dir / "audit_v2"
    assert v2_archive.exists()
    assert (v2_archive / "final_report.md").exists()
    # Check that original active ones are gone
    assert not (results_dir / "final_report.md").exists()
    assert not (results_dir / "per_tool").exists()
    assert (results_dir / "audit_v1").exists() # v1 preserved

def test_manage_previous_results_archive_with_prefix(tmp_path):
    results_dir = tmp_path / "Results"
    results_dir.mkdir()
    (results_dir / "old.txt").write_text("foo")
    
    options = AuditOptions(output=OutputOptions(retention_mode="archive", archive_name_prefix="project"))
    manage_previous_results(results_dir, options)
    
    assert (results_dir / "project_v1").exists()
    assert (results_dir / "project_v1" / "old.txt").exists()
