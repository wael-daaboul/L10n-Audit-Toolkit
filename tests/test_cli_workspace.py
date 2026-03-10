from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run_cli(tools_dir: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    python_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{tools_dir}{':' + python_path if python_path else ''}"
    return subprocess.run(
        [sys.executable, "-m", "core.cli", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )


def _write_zip(path: Path, files: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_cli_init_creates_workspace_for_flutter_project(tmp_path: Path, tools_dir: Path) -> None:
    project_root = tmp_path / "sample-app"
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;\n")

    result = _run_cli(tools_dir, project_root, "init")

    assert "Initialized workspace" in result.stdout
    config = json.loads((project_root / ".l10n-audit/config.json").read_text(encoding="utf-8"))
    assert config["project_profile"] == "flutter_getx_json"
    assert config["project_root"] == ".."
    assert (project_root / ".l10n-audit/glossary.json").exists()


def test_cli_run_uses_workspace_config_and_generates_results(tmp_path: Path, tools_dir: Path) -> None:
    project_root = tmp_path / "sample-app"
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", '{"home.title":"Home"}')
    _write(project_root / "assets/language/ar.json", '{"home.title":"الرئيسية"}')
    _write(project_root / "lib/main.dart", "'home.title'.tr;\n")

    _run_cli(tools_dir, project_root, "init")
    result = _run_cli(tools_dir, project_root, "run", "--stage", "fast")

    assert "Running audits.l10n_audit_pro" in result.stdout
    assert (project_root / ".l10n-audit/Results/final/final_audit_report.json").exists()


def test_cli_update_preserves_existing_config_values(tmp_path: Path, tools_dir: Path) -> None:
    project_root = tmp_path / "sample-app"
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;\n")

    _run_cli(tools_dir, project_root, "init")
    config_path = project_root / ".l10n-audit/config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["target_locales"] = ["ar", "fr"]
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    _run_cli(tools_dir, project_root, "update")

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["target_locales"] == ["ar", "fr"]
    assert (project_root / ".l10n-audit/config.backup.json").exists()


def test_cli_init_can_sync_templates_from_archive_url(tmp_path: Path, tools_dir: Path) -> None:
    project_root = tmp_path / "sample-app"
    _write(project_root / "pubspec.yaml", "name: sample_app")
    _write(project_root / "assets/language/en.json", "{}")
    _write(project_root / "assets/language/ar.json", "{}")
    _write(project_root / "lib/main.dart", "'home.title'.tr;\n")
    archive_path = tmp_path / "template.zip"
    _write_zip(archive_path, {"repo-main/templates/readme.txt": "hello from archive"})

    result = _run_cli(
        tools_dir,
        project_root,
        "init",
        "--from-github",
        "--repo",
        archive_path.resolve().as_uri(),
    )

    assert "GitHub templates" in result.stdout
    template_file = project_root / ".l10n-audit/toolkit-template/templates/readme.txt"
    assert template_file.exists()
    version = json.loads((project_root / ".l10n-audit/version.json").read_text(encoding="utf-8"))
    assert version["github_sync"]["extracted_files"] == 1
