from l10n_audit.models import AuditOptions, OutputOptions

def test_results_retention_defaults():
    opts = AuditOptions()
    assert opts.output.retention_mode == "overwrite"
    assert opts.output.archive_name_prefix == "audit"

def test_results_retention_custom():
    opts = AuditOptions(
        output=OutputOptions(retention_mode="archive", archive_name_prefix="test_run")
    )
    assert opts.output.retention_mode == "archive"
    assert opts.output.archive_name_prefix == "test_run"
