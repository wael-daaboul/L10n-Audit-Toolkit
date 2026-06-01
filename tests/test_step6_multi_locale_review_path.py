"""
Step 6 regression tests — multi-locale review path.

Verifies that build_review_queue() loads ALL target locales into the hydration
data stores, and that api.py immediate auto-fixes are exported per locale rather
than collapsed into a single 'ar' bucket.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(tmp_path: Path, extra_locales: list[str] | None = None) -> SimpleNamespace:
    """Return a minimal runtime-like object with en + ar + optional extra locales."""
    lang_dir = tmp_path / "assets" / "language"
    lang_dir.mkdir(parents=True)

    en_file = lang_dir / "en.json"
    en_file.write_text(json.dumps({"hello": "Hello", "bye": "Goodbye"}), encoding="utf-8")
    ar_file = lang_dir / "ar.json"
    ar_file.write_text(json.dumps({"hello": "مرحبا", "bye": "وداعا"}), encoding="utf-8")

    locale_paths: dict[str, Path] = {"en": en_file, "ar": ar_file}
    target_locales = ["ar"]

    for loc in (extra_locales or []):
        loc_file = lang_dir / f"{loc}.json"
        loc_file.write_text(json.dumps({"hello": f"hello-{loc}", "bye": f"bye-{loc}"}), encoding="utf-8")
        locale_paths[loc] = loc_file
        target_locales.append(loc)

    return SimpleNamespace(
        project_root=tmp_path,
        results_dir=tmp_path / "Results",
        en_file=en_file,
        ar_file=ar_file,
        original_en_file=en_file,
        original_ar_file=ar_file,
        locale_format="json",
        source_locale="en",
        target_locales=tuple(target_locales),
        locale_paths=locale_paths,
        locale_root=lang_dir,
        metadata={},
        ai_review={"enabled": False},
        output={"results_dir": str(tmp_path / "Results")},
        config={},
    )


# ---------------------------------------------------------------------------
# Test: build_review_queue loads all target locales
# ---------------------------------------------------------------------------

def test_build_review_queue_loads_all_target_locales(tmp_path: Path) -> None:
    """build_review_queue must include current_value for each target locale, not
    just the first one."""
    runtime = _make_runtime(tmp_path, extra_locales=["fr"])

    # Simulate two issues: one for "ar", one for "fr"
    issues = [
        {
            "key": "hello",
            "locale": "ar",
            "issue_type": "missing_translation",
            "severity": "warning",
            "message": "missing",
            "source": "ar_locale_qc",
            "candidate_value": "مرحبا-new",
            "details": {},
        },
        {
            "key": "bye",
            "locale": "fr",
            "issue_type": "missing_translation",
            "severity": "warning",
            "message": "missing",
            "source": "ar_locale_qc",
            "candidate_value": "au-revoir",
            "details": {},
        },
    ]

    from l10n_audit.reports.report_aggregator import build_review_queue

    rows = build_review_queue(issues, runtime)

    # Both locales must appear in the output
    locales_in_rows = {r["locale"] for r in rows}
    assert "ar" in locales_in_rows, "build_review_queue must include 'ar' locale rows"
    assert "fr" in locales_in_rows, "build_review_queue must include 'fr' locale rows (second target)"

    # The 'fr' row must have a non-empty old_value sourced from fr.json
    fr_rows = [r for r in rows if r["locale"] == "fr"]
    assert fr_rows, "No 'fr' rows in review queue"
    # old_value is populated from fr.json via hydration — must not be empty when key exists
    assert fr_rows[0]["old_value"] == "bye-fr", (
        f"Expected 'bye-fr' but got {fr_rows[0]['old_value']!r}. "
        "fr locale data was not loaded into _locale_data_stores."
    )


def test_build_review_queue_single_target_locale_unchanged(tmp_path: Path) -> None:
    """Single-target-locale projects must continue to work correctly."""
    runtime = _make_runtime(tmp_path)

    issues = [
        {
            "key": "hello",
            "locale": "ar",
            "issue_type": "bad_translation",
            "severity": "warning",
            "message": "check",
            "source": "ar_locale_qc",
            "candidate_value": "مرحبا-fixed",
            "details": {},
        }
    ]

    from l10n_audit.reports.report_aggregator import build_review_queue

    rows = build_review_queue(issues, runtime)
    ar_rows = [r for r in rows if r["locale"] == "ar"]
    assert ar_rows, "No 'ar' rows — single-target regression"
    assert ar_rows[0]["old_value"] == "مرحبا"


# ---------------------------------------------------------------------------
# Test: api.py immediate auto-fix iterates all target locales
# ---------------------------------------------------------------------------

def test_api_immediate_autofix_uses_locale_paths_not_hardcoded_ar(tmp_path: Path) -> None:
    """The immediate auto-fix block in api.py must iterate runtime.target_locales
    and look up each locale's file in runtime.locale_paths — not hardcode 'ar'."""
    import inspect
    import l10n_audit.api as api_module

    source = inspect.getsource(api_module)

    # The old pattern: filters by i["locale"] == "ar" OR i["locale"] == runtime.target_locales[0]
    assert 'i["locale"] == "ar"' not in source or 'auto_fixes_ar' not in source, (
        "api.py still contains the old single-locale 'auto_fixes_ar' bucket — "
        "the multi-locale loop was not applied"
    )

    # The new pattern must iterate target_locales
    assert "for _tl in runtime.target_locales" in source, (
        "api.py must iterate runtime.target_locales for per-locale auto-fixes"
    )
