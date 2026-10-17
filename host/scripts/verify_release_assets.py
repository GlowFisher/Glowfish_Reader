from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from workspace_paths import component_root

ROOT = Path(__file__).resolve().parents[1]


def verify_ui() -> int:
    dist = Path(os.environ.get("GLOWFISH_UI_DIST", component_root("ui") / "dist"))
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    count = 0
    for item in manifest["files"]:
        path = dist / item["path"]
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"UI asset hash mismatch: {path}")
        count += 1
    return count


def verify_models() -> int:
    model_root = Path(os.environ.get("GLOWFISH_OCR_MODELS", ROOT / "glowfish_reader" / "proofread" / "models"))
    lock = json.loads((component_root("ocr") / "models.lock.json").read_text(encoding="utf-8"))
    count = 0
    for item in lock["files"]:
        path = model_root / item["path"]
        if path.stat().st_size != item["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"OCR model hash mismatch: {path}")
        count += 1
    return count


if __name__ == "__main__":
    print(f"release assets verified: UI={verify_ui()}, OCR models={verify_models()}")
