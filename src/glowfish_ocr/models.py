from __future__ import annotations

import hashlib
import json
from pathlib import Path


def verify_models(lock_path: Path, model_root: Path) -> list[str]:
    lock = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    errors: list[str] = []
    for entry in lock.get("files", []):
        path = Path(model_root) / entry["path"]
        if not path.is_file():
            errors.append(f"missing:{entry['path']}")
            continue
        if path.stat().st_size != entry["bytes"]:
            errors.append(f"size:{entry['path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != entry["sha256"].lower():
            errors.append(f"sha256:{entry['path']}")
    return errors
