"""
Step 7 regression tests — report_aggregator.main() argparse fix.

Verifies that the ``--out-normalized`` argument is registered in the argparse
parser used by main(), so that the CLI entry point does not crash with
AttributeError when invoked.
"""
from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _build_parser_from_main(results_dir: Path) -> argparse.Namespace:
    """Replicate main()'s parser construction against a fake results_dir, then
    parse an empty argv so all defaults are used.  Returns the parsed Namespace."""
    from l10n_audit.reports.report_aggregator import (
        resolve_final_report_path,
        resolve_review_queue_path,
        resolve_review_projection_json_path,
    )

    # Build a minimal runtime-like object with only the attributes main() touches
    # when constructing parser defaults.
    mock_runtime = SimpleNamespace(
        results_dir=results_dir,
        project_root=results_dir.parent,
    )
    # Patch resolve_* helpers that depend on a real AuditPaths object
    with (
        patch("l10n_audit.reports.report_aggregator.resolve_final_report_path",
              return_value=results_dir / "final" / "final_audit_report_final.json"),
        patch("l10n_audit.reports.report_aggregator.resolve_review_queue_path",
              return_value=results_dir / "review" / "review_queue.xlsx"),
        patch("l10n_audit.reports.report_aggregator.resolve_review_projection_json_path",
              return_value=results_dir / "review" / "review_projection.json"),
        patch("l10n_audit.reports.report_aggregator.load_runtime",
              return_value=mock_runtime),
    ):
        # Capture the parser by temporarily replacing parse_args with a no-op
        captured: list[argparse.ArgumentParser] = []
        original_parse_args = argparse.ArgumentParser.parse_args

        def _capture_parser(self, args=None, namespace=None):
            captured.append(self)
            return original_parse_args(self, args=[], namespace=namespace)

        with patch.object(argparse.ArgumentParser, "parse_args", _capture_parser):
            import sys
            _orig_argv = sys.argv
            sys.argv = ["report_aggregator"]
            try:
                # main() calls load_runtime, then parse_args — we intercept parse_args
                # but we still need to short-circuit the rest of main() to avoid I/O
                with patch("l10n_audit.reports.report_aggregator.load_all_report_issues",
                           return_value=({}, [], [])), \
                     patch("l10n_audit.reports.report_aggregator.build_review_queue",
                           return_value=[]), \
                     patch("l10n_audit.reports.report_aggregator.summarize_issues",
                           return_value={}), \
                     patch("l10n_audit.reports.report_aggregator.safe_fix_counts",
                           return_value={"available": 0}), \
                     patch("l10n_audit.reports.report_aggregator.build_source_status",
                           return_value={}), \
                     patch("l10n_audit.reports.report_aggregator.render_markdown",
                           return_value=""), \
                     patch("l10n_audit.reports.report_aggregator.write_unified_json"), \
                     patch("l10n_audit.reports.report_aggregator.write_simple_xlsx"), \
                     patch("l10n_audit.reports.report_aggregator.write_audit_master"), \
                     patch("l10n_audit.reports.report_aggregator.build_human_review_queue",
                           return_value=[]), \
                     patch("pathlib.Path.mkdir"), \
                     patch("pathlib.Path.write_text"):
                    from l10n_audit.reports.report_aggregator import main
                    try:
                        main()
                    except Exception:
                        pass  # errors after parse_args are fine; we only need the parser
            finally:
                sys.argv = _orig_argv

    assert captured, "Could not capture argparse.ArgumentParser from main()"
    return captured[0].parse_args([])


# ---------------------------------------------------------------------------
# Test: --out-normalized is registered and accessible
# ---------------------------------------------------------------------------

def test_main_argparser_has_out_normalized(tmp_path: Path) -> None:
    """main()'s argparse parser must register --out-normalized.

    Without this argument the CLI crashes with:
        AttributeError: 'Namespace' object has no attribute 'out_normalized'
    """
    ns = _build_parser_from_main(tmp_path / "Results")
    assert hasattr(ns, "out_normalized"), (
        "--out-normalized is not registered in report_aggregator.main(). "
        "Add: parser.add_argument('--out-normalized', default=...)"
    )
    # The default must point somewhere inside results_dir / normalized
    assert "normalized" in ns.out_normalized, (
        f"--out-normalized default {ns.out_normalized!r} does not contain 'normalized'. "
        "Expected a path inside <results_dir>/normalized/."
    )


def test_main_argparser_out_normalized_default_ends_with_json(tmp_path: Path) -> None:
    """The default value for --out-normalized must be a .json path."""
    ns = _build_parser_from_main(tmp_path / "Results")
    assert ns.out_normalized.endswith(".json"), (
        f"--out-normalized default {ns.out_normalized!r} is not a .json path"
    )


def test_main_source_contains_out_normalized_argument() -> None:
    """Source-code check: report_aggregator.main() must contain the
    add_argument call so the fix is permanent and not bypassed by patching."""
    import l10n_audit.reports.report_aggregator as mod
    src = inspect.getsource(mod.main)
    assert "--out-normalized" in src, (
        "report_aggregator.main() source does not contain '--out-normalized'. "
        "The argparse fix was not applied."
    )
