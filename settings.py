"""Environment overrides and an optional, untracked local configuration file."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


def read_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Local configuration must be a JSON object.")
    return config


CONFIG = read_config(Path(os.environ.get("MEETING_CONFIG_FILE", ROOT / "config.local.json")))


def value(name: str, default: Any = "") -> Any:
    return os.environ.get(name, CONFIG.get(name, default))


def path_value(name: str, default: str) -> Path:
    path = Path(value(name, default)).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def list_value(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    selected = value(name, default)
    if isinstance(selected, str):
        selected = json.loads(selected)
    if not isinstance(selected, (list, tuple)) or any(not isinstance(item, str) for item in selected):
        raise ValueError(f"{name} must be an array of relative paths.")
    if any(Path(item).is_absolute() or ".." in Path(item).parts for item in selected):
        raise ValueError(f"{name} must stay beneath the material directory.")
    return tuple(selected)
