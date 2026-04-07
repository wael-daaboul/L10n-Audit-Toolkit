from __future__ import annotations

from pathlib import Path
from typing import Any


def load_dotenv(dotenv_path: str | Path | None = None, *args: Any, **kwargs: Any) -> bool:
    """Minimal compatibility shim for python-dotenv used in tests.

    Loads simple KEY=VALUE pairs from the target file into ``os.environ`` if the
    file exists. Missing files are a no-op and return ``False``.
    """
    import os

    target = Path(dotenv_path) if dotenv_path is not None else Path(".env")
    if not target.exists() or not target.is_file():
        return False

    loaded = False
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip())
        loaded = True

    return loaded
