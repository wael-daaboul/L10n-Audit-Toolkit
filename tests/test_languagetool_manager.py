from pathlib import Path
from types import SimpleNamespace

from l10n_audit.core.languagetool_manager import create_language_tool_session, discover_local_languagetool


def _runtime(tmp_path: Path, configured_dir: Path | None = None):
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    project_root = tmp_path
    return SimpleNamespace(
        tools_dir=tools_dir,
        project_root=project_root,
        languagetool_configured_dir=configured_dir,
    )


def _make_installation(root: Path, version: str) -> Path:
    install = root / f"LanguageTool-{version}"
    install.mkdir(parents=True, exist_ok=True)
    (install / "languagetool-server.jar").write_text("", encoding="utf-8")
    return install


def test_discover_local_languagetool_prefers_configured_dir(tmp_path: Path) -> None:
    configured = _make_installation(tmp_path / "custom", "7.0")
    _make_installation(tmp_path / "tools" / "vendor", "8.0")
    runtime = _runtime(tmp_path, configured_dir=configured)

    installation = discover_local_languagetool(runtime)

    assert installation is not None
    assert installation.root_dir == configured.resolve()


def test_discover_local_languagetool_uses_highest_dynamic_version(tmp_path: Path) -> None:
    _make_installation(tmp_path / "tools" / "vendor", "6.7")
    expected = _make_installation(tmp_path / "vendor", "7.0")
    runtime = _runtime(tmp_path)

    installation = discover_local_languagetool(runtime)

    assert installation is not None
    assert installation.root_dir == expected.resolve()


def test_create_language_tool_session_prefers_local_server(monkeypatch, tmp_path: Path) -> None:
    _make_installation(tmp_path / "tools" / "vendor", "6.9")
    runtime = _runtime(tmp_path)

    class FakeTool:
        def __init__(self, language: str, remote_server: str | None = None):
            self.language = language
            self.remote_server = remote_server

        def close(self) -> None:
            return None

    fake_module = SimpleNamespace(LanguageTool=FakeTool)
    monkeypatch.setitem(__import__("sys").modules, "language_tool_python", fake_module)
    monkeypatch.setattr("l10n_audit.core.languagetool_manager._ensure_local_server", lambda installation, port=8083: ("http://127.0.0.1:8083", "LanguageTool mode: local bundled server"))

    session = create_language_tool_session("en-US", runtime)

    assert session.tool is not None
    assert session.mode == "LanguageTool mode: local bundled server"
    assert session.tool.remote_server == "http://127.0.0.1:8083"


def test_create_language_tool_session_falls_back_when_local_missing(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)

    class FakeTool:
        def __init__(self, language: str, remote_server: str | None = None):
            self.language = language
            self.remote_server = remote_server

        def close(self) -> None:
            return None

    fake_module = SimpleNamespace(LanguageTool=FakeTool)
    monkeypatch.setitem(__import__("sys").modules, "language_tool_python", fake_module)

    session = create_language_tool_session("ar", runtime)

    assert session.tool is not None
    assert session.mode == "LanguageTool mode: cached/downloaded fallback"
    assert session.tool.remote_server is None
