from __future__ import annotations

import json
import os
from pathlib import Path


def ui_dist() -> Path:
    override = os.environ.get("GLOWFISH_UI_DIST")
    workspace = os.environ.get("GLOWFISH_WORKSPACE_ROOT")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates.append(here / "ui_dist")
    if workspace:
        candidates.append(Path(workspace) / "ui" / "dist")
    elif len(here.parents) > 2:
        candidates.append(here.parents[2] / "ui" / "dist")
    for candidate in candidates:
        manifest = candidate / "manifest.json"
        if not manifest.is_file():
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        files = payload.get("files") or []
        if not files or any(not (candidate / item["path"]).is_file() for item in files):
            raise RuntimeError(f"UI manifest references missing files: {manifest}")
        return candidate.resolve()
    raise FileNotFoundError("built UI dist not found; run the UI component build first")
