from __future__ import annotations

import json
import os
from pathlib import Path


def ui_dist() -> Path:
    override = os.environ.get("GLOWFISH_UI_DIST")
    candidates = []
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve().parent
    candidates.extend((here / "ui_dist", here.parents[1] / "components" / "ui" / "dist"))
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
