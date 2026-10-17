from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify_ui() -> int:
    dist = Path(os.environ.get("GLOWFISH_UI_DIST", ROOT / "ui" / "dist"))
    manifest = json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    count = 0
    for item in manifest["files"]:
        path = dist / item["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != item["bytes"] or digest != item["sha256"]:
            raise SystemExit(f"UI asset hash mismatch: {path}")
        count += 1
    return count


def verify_models() -> int:
    model_root_value = os.environ.get("GLOWFISH_OCR_MODELS")
    if not model_root_value:
        model_root_value = str(ROOT / "host" / "glowfish_reader" / "proofread" / "models")
    model_root = Path(model_root_value)
    lock = json.loads((ROOT / "ocr" / "models.lock.json").read_text(encoding="utf-8"))
    count = 0
    for item in lock["files"]:
        path = model_root / item["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.stat().st_size != item["bytes"] or digest != item["sha256"]:
            raise SystemExit(f"OCR model hash mismatch: {path}")
        count += 1
    return count


parser = argparse.ArgumentParser()
parser.add_argument("--skip-models", action="store_true")
args = parser.parse_args()

ui_count = verify_ui()
model_count = 0 if args.skip_models else verify_models()
print(f"release assets verified: UI={ui_count}, OCR models={model_count}")
