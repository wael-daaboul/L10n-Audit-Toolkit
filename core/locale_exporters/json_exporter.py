from __future__ import annotations

import json
from pathlib import Path


def export_json_locale(mapping: dict[str, object], path: Path) -> list[Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {key: mapping[key] for key in sorted(mapping)}
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    return [path]
