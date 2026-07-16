from __future__ import annotations

import os
from pathlib import Path

HOST_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_NAMES = ("contracts", "ui", "ocr", "account")


def workspace_root() -> Path:
    override = os.environ.get("GLOWFISH_WORKSPACE_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    parent = HOST_ROOT.parent
    if all((parent / name).is_dir() for name in COMPONENT_NAMES):
        return parent.resolve()

    return HOST_ROOT


def component_root(name: str) -> Path:
    if name not in COMPONENT_NAMES:
        raise ValueError(f"unknown component: {name}")
    root = workspace_root()
    if root == HOST_ROOT:
        return HOST_ROOT / "components" / name
    return root / name
