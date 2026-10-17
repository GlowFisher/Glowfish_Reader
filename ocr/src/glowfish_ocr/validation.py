from __future__ import annotations

import json
from pathlib import Path

SUPPORTED_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


class OcrInputUnavailableError(ValueError):
    """Input cannot be sent to an OCR worker; retrying another runtime is unsafe."""

    error_type = "ocr_input_unavailable"


def validate_ocr_input(image_dir: Path, output_path: Path, progress_path: Path | None = None) -> None:
    image_dir = Path(image_dir)
    if not image_dir.is_dir():
        raise OcrInputUnavailableError(f"image directory is unavailable: {image_dir}")
    if not any(p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES for p in image_dir.iterdir()):
        raise OcrInputUnavailableError("image directory has no supported images")
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        if progress_path is not None:
            Path(progress_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OcrInputUnavailableError(f"output directory is unavailable: {exc}") from exc


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
