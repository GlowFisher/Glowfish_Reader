# -*- coding: utf-8 -*-
from pathlib import Path

import engines


ROOT = Path(__file__).resolve().parent


def read_static(name):
    return (ROOT.parents[1] / "components" / "ui" / "dist" / name).read_text(encoding="utf-8")


def test_settings_engine_label_uses_actual_onnx_engine_value():
    settings = read_static("settings.js")
    assert '["", "满血版"]' in settings
    assert '["ppocrv6_onnx", "快速版"]' in settings
    assert "轻量版" not in settings
    assert "PP-OCRv6 medium" not in settings
    assert "ppocrv6_high" not in settings
    assert '["onnx", "快速"]' not in settings
    assert 'settings.engine_pref === "onnx"' in settings
    assert 'settings.engine_pref = "ppocrv6_onnx"' in settings


def test_legacy_onnx_alias_still_resolves_to_ppocrv6_onnx():
    assert engines.engine_name("onnx") == "ppocrv6_onnx"


def test_blank_engine_pref_resolves_to_high_accuracy_full_power():
    """满血档 = ONNX 高精（打包版唯一能跑的满血档；Paddle 档需额外解释器，仅 dev 用）。"""
    assert engines.engine_name("") == "ppocrv6_onnx_high"
