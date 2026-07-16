from __future__ import annotations

import json
from pathlib import Path


def read_ocr_result(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OCR output must be a JSON object")
    for page_id, page in data.items():
        if page_id == "_meta":
            continue
        if not isinstance(page, dict) or not isinstance(page.get("lines"), list):
            raise ValueError(f"Invalid OCR page contract: {page_id}")
        for line in page["lines"]:
            if not isinstance(line, dict) or not {"text", "box", "score"}.issubset(line):
                raise ValueError(f"Invalid OCR line contract on page: {page_id}")
    return data
