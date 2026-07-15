# -*- coding: utf-8 -*-
import importlib.util
import sys
import types
from pathlib import Path


def load_desktop_app_with_ocr(monkeypatch, engine):
    calls = []
    logging_modes = []

    def make_mod(name):
        mod = types.ModuleType(name)
        mod.main = lambda: calls.append(name)
        return mod

    monkeypatch.setitem(sys.modules, "recognize", make_mod("recognize"))
    monkeypatch.setitem(sys.modules, "recognize_ppocrv6", make_mod("recognize_ppocrv6"))
    monkeypatch.setitem(sys.modules, "recognize_ppocrv6_onnx", make_mod("recognize_ppocrv6_onnx"))
    logging_mod = types.ModuleType("runtime_logging")
    logging_mod.configure_runtime_logging = lambda mode: logging_modes.append(mode)
    monkeypatch.setitem(sys.modules, "runtime_logging", logging_mod)
    monkeypatch.setattr(sys, "argv", ["GlowFish.exe", "--ocr", engine])
    spec = importlib.util.spec_from_file_location("desktop_app_ocr_dispatch", Path(__file__).with_name("desktop_app.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return calls, logging_modes


def test_ocr_child_dispatches_ppocrv6_to_full_engine(monkeypatch):
    assert load_desktop_app_with_ocr(monkeypatch, "ppocrv6") == (["recognize_ppocrv6"], ["ocr"])


def test_ocr_child_dispatches_ppocrv6_onnx_to_lightweight_engine(monkeypatch):
    assert load_desktop_app_with_ocr(monkeypatch, "ppocrv6_onnx") == (["recognize_ppocrv6_onnx"], ["ocr"])


def test_ocr_child_dispatches_onnx_high_to_onnx_engine(monkeypatch):
    """满血档跑 recognize_ppocrv6_onnx（老的 ppocrv6_high 已作废删除）。"""
    assert load_desktop_app_with_ocr(monkeypatch, "ppocrv6_onnx_high") == (["recognize_ppocrv6_onnx"], ["ocr"])
