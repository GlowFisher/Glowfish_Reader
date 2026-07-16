from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_ENGINE = "ppocrv6_onnx_high"
ONNX_HIGH_ENGINE = "ppocrv6_onnx_high"
OFFICIAL_ENGINE = "ppocrv6"
LIGHTWEIGHT_ENGINE = "ppocrv6_onnx"
ENGINE_ALIASES = {"onnx": LIGHTWEIGHT_ENGINE}


@dataclass(frozen=True)
class EngineSpec:
    name: str
    script: str
    params: Mapping[str, Any]
    uses_current_python: bool


ENGINE_SPECS = {
    ONNX_HIGH_ENGINE: EngineSpec(ONNX_HIGH_ENGINE, "recognize_ppocrv6_onnx.py", {
        "ocr_version": "PP-OCRv6", "lang": "chinese_cht", "profile": "high_accuracy",
        "column_rescue": True, "text_det_box_thresh": 0.45,
    }, True),
    OFFICIAL_ENGINE: EngineSpec(OFFICIAL_ENGINE, "recognize_ppocrv6.py", {
        "ocr_version": "PP-OCRv6", "lang": "chinese_cht", "column_rescue": True,
    }, False),
    LIGHTWEIGHT_ENGINE: EngineSpec(LIGHTWEIGHT_ENGINE, "recognize_ppocrv6_onnx.py", {
        "ocr_version": "PP-OCRv6", "lang": "chinese_cht",
        "text_det_limit_side_len": 960, "text_det_limit_type": "max",
    }, True),
    "paddle": EngineSpec("paddle", "recognize.py", {}, False),
}


def normalize_engine(name: str | None) -> str:
    normalized = DEFAULT_ENGINE if name in (None, "") else ENGINE_ALIASES.get(name, name)
    return normalized if normalized in ENGINE_SPECS else DEFAULT_ENGINE


def resolve_engine(
    name: str | None,
    legacy_dir: Path,
    paddle_python: Path | None = None,
    desktop_executable: Path | None = None,
) -> tuple[str, list[str], dict[str, Any]]:
    normalized = normalize_engine(name)
    spec = ENGINE_SPECS[normalized]
    if spec.uses_current_python and desktop_executable is not None:
        executable = Path(desktop_executable).resolve()
        return normalized, [str(executable), "--ocr", normalized], dict(spec.params)
    python = Path(sys.executable) if spec.uses_current_python else paddle_python
    if python is None:
        raise RuntimeError(f"OCR engine '{normalized}' requires an explicitly configured Paddle Python interpreter")
    return normalized, [str(python), str(legacy_dir / spec.script)], dict(spec.params)
