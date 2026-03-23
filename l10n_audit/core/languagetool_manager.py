#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_LOCAL_PORT = 8083
SERVER_READY_PATH = "/v2/languages"
STARTUP_WAIT_SECONDS = 8.0
_STARTED_PROCESSES: dict[int, subprocess.Popen[bytes]] = {}


@dataclass(frozen=True)
class LocalLanguageToolInstallation:
    root_dir: Path
    server_jar: Path
    commandline_jar: Path | None


@dataclass
class LanguageToolSession:
    tool: Any | None
    mode: str
    note: str = ""

    def close(self) -> None:
        if self.tool is None:
            return
        close = getattr(self.tool, "close", None)
        if callable(close):
            close()


def _version_sort_key(path: Path) -> tuple[Any, ...]:
    version_text = path.name.split("LanguageTool-", 1)[-1]
    parts: list[Any] = []
    for token in version_text.replace("-", ".").split("."):
        if token.isdigit():
            parts.append(int(token))
        else:
            parts.append(token.casefold())
    return tuple(parts)


def _candidate_roots(runtime) -> list[Path]:
    roots = [
        runtime.tools_dir / "vendor",
        runtime.project_root / "tools" / "vendor",
        runtime.project_root / "vendor",
    ]
    unique: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _build_installation(path: Path) -> LocalLanguageToolInstallation | None:
    server_jar = path / "languagetool-server.jar"
    if not server_jar.exists():
        return None
    commandline_jar = path / "languagetool-commandline.jar"
    return LocalLanguageToolInstallation(
        root_dir=path.resolve(),
        server_jar=server_jar.resolve(),
        commandline_jar=commandline_jar.resolve() if commandline_jar.exists() else None,
    )


def discover_local_languagetool(runtime) -> LocalLanguageToolInstallation | None:
    configured = getattr(runtime, "languagetool_configured_dir", None)
    if configured:
        installation = _build_installation(Path(configured))
        if installation is not None:
            return installation

    matches: list[Path] = []
    for root in _candidate_roots(runtime):
        if not root.exists():
            continue
        for candidate in root.iterdir():
            if candidate.is_dir() and candidate.name.startswith("LanguageTool-"):
                matches.append(candidate.resolve())

    for candidate in sorted(matches, key=_version_sort_key, reverse=True):
        installation = _build_installation(candidate)
        if installation is not None:
            return installation
    return None


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _server_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}{SERVER_READY_PATH}", timeout=0.5) as response:
            return 200 <= getattr(response, "status", 0) < 500
    except URLError:
        return False
    except OSError:
        return False


def _ensure_local_server(installation: LocalLanguageToolInstallation, port: int = DEFAULT_LOCAL_PORT) -> tuple[str, str]:
    if _server_ready(port):
        return f"http://127.0.0.1:{port}", "LanguageTool mode: local bundled server"
    if _port_open(port):
        raise RuntimeError(f"Port {port} is already in use by a non-LanguageTool process.")

    if not shutil.which("java"):
        raise RuntimeError("Java runtime not available for local LanguageTool.")

    libs_glob = installation.root_dir / "libs" / "*"
    classpath = os.pathsep.join([str(installation.server_jar), str(libs_glob)])
    command = [
        "java",
        "-cp",
        classpath,
        "org.languagetool.server.HTTPServer",
        "--port",
        str(port),
    ]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _STARTED_PROCESSES[port] = process

    deadline = time.time() + STARTUP_WAIT_SECONDS
    while time.time() < deadline:
        if _server_ready(port):
            return f"http://127.0.0.1:{port}", "LanguageTool mode: local bundled server"
        if process.poll() is not None:
            raise RuntimeError("Local LanguageTool server exited during startup.")
        time.sleep(0.25)

    raise RuntimeError("Local LanguageTool server did not become ready in time.")


def create_language_tool_session(language: str, runtime, *, port: int = DEFAULT_LOCAL_PORT) -> LanguageToolSession:
    try:
        import language_tool_python  # type: ignore
    except Exception as exc:
        return LanguageToolSession(None, "rule-based", f"language-tool-python is unavailable: {exc}")

    installation = discover_local_languagetool(runtime)
    explicitly_configured = getattr(runtime, "languagetool_configured_dir", None) is not None

    if installation is not None:
        try:
            endpoint, mode = _ensure_local_server(installation, port=port)
            tool = language_tool_python.LanguageTool(language, remote_server=endpoint)
            return LanguageToolSession(tool, mode, f"Using local installation at {installation.root_dir}")
        except Exception as exc:
            if explicitly_configured:
                raise RuntimeError(f"Configured LanguageTool directory could not be used: {exc}") from exc
            return LanguageToolSession(None, "rule-based", f"Local bundled LanguageTool was found but could not start: {exc}")

    try:
        tool = language_tool_python.LanguageTool(language)
        return LanguageToolSession(tool, "LanguageTool mode: cached/downloaded fallback", "Using language-tool-python fallback.")
    except Exception as exc:
        return LanguageToolSession(None, "rule-based", f"LanguageTool fallback unavailable: {exc}")
