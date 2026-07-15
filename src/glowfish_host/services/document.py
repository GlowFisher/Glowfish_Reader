from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class DocumentService:
    """Lossless proof.json persistence; schema migration is deliberately separate."""

    def load(self, path: Path) -> dict[str, Any]:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("proof document must be a JSON object")
        return value

    def save(self, path: Path, document: dict[str, Any]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
