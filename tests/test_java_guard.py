import os
import pytest
from unittest.mock import patch
from l10n_audit.core.utils import check_java_available

def test_check_java_skip_env():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "true"}):
        assert check_java_available() is True

def test_check_java_mock_missing():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "false"}):
        with patch("shutil.which", return_value=None):
            assert check_java_available() is False

def test_check_java_mock_found():
    with patch.dict(os.environ, {"L10N_SKIP_JAVA_CHECK": "false"}):
        with patch("shutil.which", return_value="/usr/bin/java"):
            assert check_java_available() is True


# ---------------------------------------------------------------------------
# Step 3 regression tests: Java prerequisite scoped to grammar stages only
# ---------------------------------------------------------------------------

import subprocess
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch, MagicMock


def _make_minimal_runtime(tmp_path: Path) -> SimpleNamespace:
    """Return a minimal runtime-like object for _dispatch_stage() calls."""
    en_file = tmp_path / "en.json"
    ar_file = tmp_path / "ar.json"
    en_file.write_text('{"hello": "Hello"}', encoding="utf-8")
    ar_file.write_text('{"hello": "مرحبا"}', encoding="utf-8")
    return SimpleNamespace(
        project_root=tmp_path,
        results_dir=tmp_path / "Results",
        en_file=en_file,
        ar_file=ar_file,
        original_en_file=en_file,
        original_ar_file=ar_file,
        locale_format="json",
        source_locale="en",
        target_locales=("ar",),
        locale_paths={"ar": ar_file},
        locale_root=tmp_path,
        metadata={},
        ai_review={"enabled": False},
        output={"results_dir": str(tmp_path / "Results")},
        config={},
    )


def _make_options(stage: str, tmp_path: Path):
    """Return a minimal AuditOptions-like object for _dispatch_stage()."""
    from types import SimpleNamespace as SN

    return SN(
        stage=stage,
        ai_review=SN(enabled=False),
        write_reports=False,
        output=SN(results_dir=str(tmp_path / "Results")),
        effective_output_dir=lambda base: base,
        verbose=False,
    )


def test_grammar_stage_raises_runtime_error_when_java_missing(tmp_path: Path) -> None:
    """_dispatch_stage('grammar') must raise RuntimeError when Java is absent."""
    from l10n_audit.core.engine import _dispatch_stage

    runtime = _make_minimal_runtime(tmp_path)
    options = _make_options("grammar", tmp_path)

    with patch("subprocess.run", side_effect=FileNotFoundError("java not found")):
        with pytest.raises(RuntimeError, match="Java is required"):
            _dispatch_stage("grammar", runtime, options, ai_provider=None)


def test_full_stage_raises_runtime_error_when_java_missing(tmp_path: Path) -> None:
    """_dispatch_stage('full') must raise RuntimeError when Java is absent."""
    from l10n_audit.core.engine import _dispatch_stage

    runtime = _make_minimal_runtime(tmp_path)
    options = _make_options("full", tmp_path)

    with patch("subprocess.run", side_effect=FileNotFoundError("java not found")):
        with pytest.raises(RuntimeError, match="Java is required"):
            _dispatch_stage("full", runtime, options, ai_provider=None)


def test_reports_stage_does_not_require_java(tmp_path: Path) -> None:
    """_dispatch_stage('reports') must NOT call check_prerequisites() and must
    not raise when Java is absent."""
    from l10n_audit.core.engine import _dispatch_stage

    runtime = _make_minimal_runtime(tmp_path)
    options = _make_options("reports", tmp_path)

    # Patch subprocess.run to simulate Java absence; it must never be reached
    # for the 'reports' stage.
    java_check_called = []

    def fake_subprocess_run(cmd, **kwargs):
        if "java" in (cmd or []):
            java_check_called.append(True)
            raise FileNotFoundError("java not found")
        return MagicMock(returncode=0)

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        # 'reports' stage with write_reports=False is a no-op; must not raise
        try:
            _dispatch_stage("reports", runtime, options, ai_provider=None)
        except Exception as exc:
            # Any exception that is NOT a Java prerequisite error is acceptable
            assert "Java" not in str(exc), (
                f"reports stage must not fail because of Java: {exc}"
            )

    assert not java_check_called, (
        "check_prerequisites must not have been called for the 'reports' stage"
    )


def test_non_grammar_stages_skip_java_check(tmp_path: Path) -> None:
    """ar-qc, ar-semantic, terminology, placeholders, icu, autofix, ai-review
    stages must all skip the Java prerequisite check."""
    from l10n_audit.core.engine import _dispatch_stage

    runtime = _make_minimal_runtime(tmp_path)
    java_check_called = []

    def fake_subprocess_run(cmd, **kwargs):
        if "java" in (cmd or []):
            java_check_called.append(True)
            raise FileNotFoundError("java not found")
        return MagicMock(returncode=0)

    non_grammar_stages = ["ar-qc", "ar-semantic", "terminology", "placeholders", "icu", "autofix"]

    for stage in non_grammar_stages:
        java_check_called.clear()
        options = _make_options(stage, tmp_path)
        with patch("subprocess.run", side_effect=fake_subprocess_run):
            try:
                _dispatch_stage(stage, runtime, options, ai_provider=None)
            except Exception as exc:
                assert "Java" not in str(exc), (
                    f"Stage '{stage}' must not fail because of Java: {exc}"
                )
        assert not java_check_called, (
            f"check_prerequisites must not have been called for stage '{stage}'"
        )
