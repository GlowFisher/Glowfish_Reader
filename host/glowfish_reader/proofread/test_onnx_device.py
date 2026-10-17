# -*- coding: utf-8 -*-
"""轻量档（ONNX Runtime）的识别设备选择与 GPU 回落。

背景：轻量档 GPU 实测零提速（推理仅占 41% 且 GPU 略慢，其余是 PIL/numpy 的 CPU 活），
故默认 cpu、gpu 为显式选项。这些测试锁住「默认不变 + 显卡起不来不崩」两条底线。
"""
import pytest

import recognize_ppocrv6_onnx as o


class FakePaddleOCR:
    """构造时按 device 决定崩不崩，模拟 paddlex 的 _check_device_support。"""

    def __init__(self, gpu_ok=False):
        self.gpu_ok = gpu_ok
        self.built_with = []

    def __call__(self, **kwargs):
        self.built_with.append(kwargs.get("device"))
        if str(kwargs.get("device", "")).startswith("gpu") and not self.gpu_ok:
            raise RuntimeError("`CUDAExecutionProvider` is not available.")
        return object()


@pytest.mark.parametrize("env, has_cuda, expected", [
    (None, False, "cpu"),          # 默认：不碰显卡
    (None, True, "cpu"),           # 就算装了 GPU 轮子，默认也仍是 cpu（实测无收益）
    ("cpu", True, "cpu"),
    ("auto", True, "gpu:0"),       # auto 才按 provider 决定
    ("auto", False, "cpu"),
    ("gpu", False, "gpu:0"),       # 显式要 GPU：先返回 gpu，起不来再由 _build_engine 回落
    ("gpu:1", True, "gpu:1"),
    ("GPU:0", True, "gpu:0"),      # 大小写不敏感
    ("nonsense", True, "cpu"),     # 未知取值不猜，退回 cpu
])
def test_resolve_device(monkeypatch, env, has_cuda, expected):
    monkeypatch.delenv("SHUPAI_OCR_DEVICE", raising=False)
    if env is not None:
        monkeypatch.setenv("SHUPAI_OCR_DEVICE", env)
    monkeypatch.setattr(o, "_cuda_provider_available", lambda: has_cuda)
    assert o._resolve_device() == expected


def _patch_paddleocr(monkeypatch, fake):
    monkeypatch.setattr(o, "_ensure_paddlex_env", lambda: None)
    import sys
    import types
    mod = types.ModuleType("paddleocr")
    mod.PaddleOCR = fake
    monkeypatch.setitem(sys.modules, "paddleocr", mod)


def test_forced_gpu_without_cuda_falls_back_to_cpu(monkeypatch, capsys):
    """没显卡还硬选 GPU：警告一句、回落 CPU，绝不让识别任务崩掉。"""
    monkeypatch.setenv("SHUPAI_OCR_DEVICE", "gpu")
    fake = FakePaddleOCR(gpu_ok=False)
    _patch_paddleocr(monkeypatch, fake)

    o._build_engine({})

    assert fake.built_with == ["gpu:0", "cpu"]      # 先试 GPU，再回落
    assert o.ACTIVE_DEVICE == "cpu"
    assert "GPU OCR unavailable" in capsys.readouterr().err


def test_cpu_construction_failure_is_not_swallowed(monkeypatch):
    """回落只针对 GPU；CPU 都起不来说明真坏了，必须抛出去。"""
    monkeypatch.setenv("SHUPAI_OCR_DEVICE", "cpu")

    def boom(**kwargs):
        raise RuntimeError("model files missing")

    _patch_paddleocr(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="model files missing"):
        o._build_engine({})


def test_gpu_success_records_active_device(monkeypatch):
    monkeypatch.setenv("SHUPAI_OCR_DEVICE", "gpu:0")
    fake = FakePaddleOCR(gpu_ok=True)
    _patch_paddleocr(monkeypatch, fake)

    o._build_engine({})

    assert fake.built_with == ["gpu:0"]
    assert o.ACTIVE_DEVICE == "gpu:0"


def test_config_device_overrides_env(monkeypatch):
    """bench 的 A/B 用 config 显式给 device，须压过环境变量。"""
    monkeypatch.setenv("SHUPAI_OCR_DEVICE", "cpu")
    fake = FakePaddleOCR(gpu_ok=True)
    _patch_paddleocr(monkeypatch, fake)

    o._build_engine({"device": "gpu:0"})

    assert fake.built_with == ["gpu:0"]
    assert o.ACTIVE_DEVICE == "gpu:0"
