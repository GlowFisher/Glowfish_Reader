# -*- coding: utf-8 -*-
"""OCR engine registry."""
import sys
from pathlib import Path

import appconfig

HERE = Path(__file__).resolve().parent

ENGINES = {
    "ppocrv6_onnx_high": {
        "label": "PP-OCRv6 (ONNX Runtime, high accuracy vertical historical docs)",
        "python": "self",
        "script": "recognize_ppocrv6_onnx.py",
        # 满血 ONNX 档：det 自适应尺度（同 ppocrv6_onnx）+ 五层后处理增强。
        # column_rescue 不在 params 里——2026-07-08 消融 ΔF1 = 0.000，整页 det 修好后
        # 列救援已无信息可捞；这里沿用轻量档的 uncovered_columns 兜底即可。
        "params": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht",
                   "profile": "high_accuracy", "text_det_box_thresh": 0.45},
    },
    "ppocrv6": {
        "label": "PP-OCRv6 (official PaddleOCR local)",
        "python": None,
        "script": "recognize_ppocrv6.py",
        "params": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht", "column_rescue": True},
    },
    "ppocrv6_onnx": {
        "label": "PP-OCRv6 (ONNX Runtime, lightweight)",
        "python": "self",
        "script": "recognize_ppocrv6_onnx.py",
        # 与满血档同一后端（paddleocr.PaddleOCR + onnxruntime 推理），吃同一份 pipeline 配置，
        # 同样中 det 尺度陷阱 + box_thresh 被从模型自带的 0.45 抬到 0.6，故同样显式调回 0.45。
        # 差别只在没有 profile=high_accuracy 那几层后处理。
        "params": {"ocr_version": "PP-OCRv6", "lang": "chinese_cht", "text_det_box_thresh": 0.45},
    },
    "paddle": {
        "label": "PaddleOCR(chinese_cht)",
        "python": None,
        "script": "recognize.py",
        "params": {},
    },
}

# 满血档只有一个：ONNX 高精。旧的 Paddle 满血档 ppocrv6_high 已作废删除（见
# docs/OCR_满血版设计.md）。ppocrv6 保留为 dev/诊断用的官方 PaddleOCR 对照路径。
DEFAULT_ENGINE = "ppocrv6_onnx_high"
ONNX_HIGH_ENGINE = "ppocrv6_onnx_high"
OFFICIAL_ENGINE = "ppocrv6"
LIGHTWEIGHT_ENGINE = "ppocrv6_onnx"
ENGINE_ALIASES = {
    "onnx": LIGHTWEIGHT_ENGINE,
}


def engine_name(name=None):
    """Normalize an engine name without probing interpreter availability."""
    if name is None:
        stored = appconfig.get_engine()
        name = DEFAULT_ENGINE if stored in (None, "", OFFICIAL_ENGINE) else stored
    elif name == "":
        name = DEFAULT_ENGINE
    name = ENGINE_ALIASES.get(name, name)
    return name if name in ENGINES else DEFAULT_ENGINE


def resolve_engine(name=None):
    """Return (engine_name, argv_prefix, params) for an OCR child process."""
    name = engine_name(name)
    spec = ENGINES[name]
    py = spec.get("python")
    params = dict(spec.get("params") or {})
    if py == "self":
        if getattr(sys, "frozen", False):
            return name, [sys.executable, "--ocr", name], params
        return name, [sys.executable, str(HERE / spec["script"])], params
    if not py:
        py = appconfig.get_paddle_python()
    if not py:
        raise RuntimeError(
            f"No Python interpreter found for OCR engine '{name}'. Set SHUPAI_PADDLE_PY "
            f"or install the PaddleOCR environment."
        )
    return name, [str(py), str(HERE / spec["script"])], params
