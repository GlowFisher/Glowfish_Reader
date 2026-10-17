# -*- coding: utf-8 -*-
"""det_scale 的纯数学单测（不碰 PaddleOCR）。

守住三条不变量：
  1. 大图必须被缩到「缩放后列距≈目标值」，否则 DB 置信度塌陷 → 整列漏检；
  2. 小图绝不放大（limit ≥ 长边 ⇒ limit_type=max 语义下不缩放）；
  3. 关掉开关能完全回滚成 PaddleOCR 原生默认（返回空覆盖）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import det_scale  # noqa: E402


def _cols(centers, width=200):
    return [(c - width / 2, 0, c + width / 2, 1000) for c in centers]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("SHUPAI_DET_ADAPTIVE_SCALE", "SHUPAI_DET_PITCH_MAX",
                "SHUPAI_DET_LIMIT_SIDE_LEN"):
        monkeypatch.delenv(key, raising=False)


def test_pitch_is_median_gap_of_column_centers():
    assert det_scale.column_pitch(_cols([100, 500, 900, 1300])) == 400


def test_pitch_median_ignores_one_outlier_gap():
    # 夹注小字列/短标题列会拉偏均值，中位数不受单个异常间距影响
    assert det_scale.column_pitch(_cols([100, 500, 520, 920])) == 400


def test_pitch_single_column_falls_back_to_core_width():
    # 列框含 ±35% pad ⇒ span = 宽 / 1.7
    assert det_scale.column_pitch([(0, 0, 170, 100)]) == pytest.approx(100.0)


def test_pitch_empty_is_zero():
    assert det_scale.column_pitch([]) == 0.0


def test_large_page_downscales_to_target_pitch():
    """证据页口径：4531×6786、列距 404 → 缩放后列距应落到目标值附近。"""
    scale = det_scale.scale_for(404.0)
    override = det_scale.det_overrides(6786, scale)
    assert override["text_det_limit_type"] == "max"
    assert scale == pytest.approx(det_scale.MIN_SCALE)  # absolute downscale floor wins here
    assert override["text_det_limit_side_len"] == round(6786 * scale)


def test_small_page_is_never_upscaled():
    """628×1007、列距 56（已在甜点区）→ scale 封顶 1.0，limit≥长边 ⇒ 实际不缩放。"""
    scale = det_scale.scale_for(56.0)
    assert scale == 1.0
    assert det_scale.det_overrides(1007, scale)["text_det_limit_side_len"] == 1007


def test_unknown_pitch_falls_back_to_flat_limit():
    assert det_scale.scale_for(0) == 0.0
    assert det_scale.det_overrides(6000, 0.0) == {
        "text_det_limit_side_len": det_scale.FLAT_LIMIT, "text_det_limit_type": "max"}


def test_limit_is_clamped_to_paddle_bounds():
    assert det_scale.det_overrides(10 ** 6, 1.0)["text_det_limit_side_len"] == det_scale.MAX_LIMIT
    assert det_scale.det_overrides(10, 0.001)["text_det_limit_side_len"] == det_scale.MIN_LIMIT


def test_narrow_crop_keeps_paddle_short_side_upscale():
    """竖排单列裁剪图是极端长条（实测 45×811）。pipeline 默认的 64/min 会把短边放大到 64，
    det 才读得成一行；换成 limit_type=max 会丢掉这层保底、每个字被切成一段。"""
    override = det_scale.det_for_size((45, 811), 1.0)
    assert override == {"text_det_limit_side_len": 64, "text_det_limit_type": "min"}


def test_short_side_floor_applies_after_scaling():
    # 850×6740 的列裁剪图缩到 0.1436 后短边 122 ≥ 64 → 正常走 max
    assert det_scale.det_for_size((850, 6740), 0.1436)["text_det_limit_type"] == "max"


def test_scale_is_clamped_not_abandoned_when_short_side_would_break_floor():
    """原短边 ≥64、缩放后 <64：必须把 scale 夹到「短边正好 64」，而不是交还 64/min。
    交还 64/min 时 PaddleX 见短边 400≥64 直接 ratio=1、完全不缩，尺度陷阱原样复现。"""
    override = det_scale.det_for_size((400, 5900), 0.05)   # 期望短边 20，破底
    assert override["text_det_limit_type"] == "max"
    clamped = 64 / 400
    assert override["text_det_limit_side_len"] == round(5900 * clamped)  # 仍在缩，只是不破 64


def test_full_page_unaffected_by_short_side_floor():
    # 628×1007 整页短边 628，任何合理 scale 都不触发保底
    assert det_scale.det_for_size((628, 1007), 1.0) == {
        "text_det_limit_side_len": 1007, "text_det_limit_type": "max"}


def test_disabling_adaptive_returns_no_override(monkeypatch):
    monkeypatch.setenv("SHUPAI_DET_ADAPTIVE_SCALE", "0")
    assert det_scale.det_overrides(6786, 0.15) == {}


def test_target_pitch_is_env_tunable(monkeypatch):
    monkeypatch.setenv("SHUPAI_DET_PITCH_MAX", "100")
    assert 200 * det_scale.scale_for(200.0) == pytest.approx(100.0, abs=0.5)

