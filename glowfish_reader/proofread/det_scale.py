# -*- coding: utf-8 -*-
"""按列距自适应缩放 det 输入尺度。

**为什么需要**：PaddleX 的 `configs/pipelines/OCR.yaml` 给 TextDetection 写死
`limit_side_len: 64 / limit_type: min`（短边≥64 就不缩放 ⇒ 大图原尺寸进 det，只被
`max_side_limit: 4000` 硬夹），覆盖了 `PP-OCRv6_medium_det` 自身在 PaddleX
`_TEXT_DET_MAX_LIMIT_MODELS` 里的设计默认 `960/max`。于是 4531×6786 的影印页以
2671×4000 送进 DB 检测器，缩放后列间距 243px，远超训练尺度 → 笔画松散的列 DB 置信度
先跌破 box_thresh → **整列被丢弃**。

**为什么不是定值**：DB 检测器对列间距的容忍度是一个**区间**，不是单点。实测：

    列距 50-120px：检测稳定，不漏不碎
    列距 120-200px：开始出现碎片
    列距 >200px：碎片严重
    列距 <40px：列间粘连

故策略为「只要缩进安全区间就停手，绝不多缩」——宽列距文档（族谱）不会再被压到 13%，
窄列距小图保持不动。同时设绝对保底 MIN_SCALE=0.35，无论列距多大，压缩后长边不低于
原长边的 35%，防止笔画细节丢失导致真字漏检。

**同一 scale 必须同时用于列裁剪**：裁剪图（如 850×6740）长边同样被夹到 4000，
不覆盖的话尺度陷阱原样复现。

开关：
  SHUPAI_DET_ADAPTIVE_SCALE=0     关闭自适应，回到 PaddleOCR 原生默认
  SHUPAI_DET_PITCH_MAX=120        安全区上界（列距高于此值才缩小）
  SHUPAI_DET_PITCH_MIN=60         安全区下界（列距低于此值才放大）
  SHUPAI_DET_MIN_SCALE=0.35       绝对保底缩放比
  SHUPAI_DET_LIMIT_SIDE_LEN=1600  估不出列距时的 flat 兜底
"""
import os

PITCH_MIN  = 60.0      # 安全区下界：列距低于此值 → 列间粘连风险 → 放大
PITCH_MAX  = 120.0     # 安全区上界：列距高于此值 → 碎片风险 → 缩小
MIN_SCALE  = 0.35      # 绝对保底：不管列距多大，压缩后长边 ≥ 原长边 × 35%
FLAT_LIMIT = 1600      # 估不出列距时的兜底（手写全集总分最高的定值）
MIN_LIMIT  = 64        # PaddleOCR 自身下限
MAX_LIMIT  = 4000      # PaddleX max_side_limit
MIN_SHORT  = 64        # det 短边下限：低于它必须让 PaddleX 放大，见 det_overrides
PAD_RATIO  = 0.35      # find_vertical_text_columns 的 pad_x 比例（相对原始 span）


def _flag(name, default="1"):
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "")


def _num(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def adaptive_enabled():
    return _flag("SHUPAI_DET_ADAPTIVE_SCALE", "1")


def column_pitch(columns):
    """列中心的中位间距（px）。0 = 估不出。

    用中位数而非均值：夹注小字列、短标题列会拉偏均值。单列时退回核心宽度
    （列框含 ±PAD_RATIO 的 pad，span = 宽 / (1+2·PAD_RATIO)）。
    """
    boxes = [b for b in (columns or []) if b is not None]
    if not boxes:
        return 0.0
    centers = sorted((float(b[0]) + float(b[2])) / 2.0 for b in boxes)
    if len(centers) < 2:
        box = boxes[0]
        return (float(box[2]) - float(box[0])) / (1.0 + 2.0 * PAD_RATIO)
    gaps = sorted(centers[i + 1] - centers[i] for i in range(len(centers) - 1))
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0


def scale_for(pitch):
    """原图 → det 输入的缩放比。≤0 表示估不出列距（走 FLAT_LIMIT 兜底）。

    策略：安全区间 [PITCH_MIN, PITCH_MAX]。在区间内不缩放（scale=1.0）；
    高于上界按上界缩小；低于下界按下界放大。所有缩放均受 MIN_SCALE 和 1.0 夹持。
    """
    if not pitch or pitch <= 0:
        return 0.0
    pitch_min = _num("SHUPAI_DET_PITCH_MIN", PITCH_MIN)
    pitch_max = _num("SHUPAI_DET_PITCH_MAX", PITCH_MAX)
    min_scale = _num("SHUPAI_DET_MIN_SCALE", MIN_SCALE)
    if pitch < pitch_min:
        return min(1.0, pitch_min / float(pitch))
    if pitch > pitch_max:
        return max(min_scale, pitch_max / float(pitch))
    return 1.0


def det_for_size(size, scale):
    """size = PIL 的 (w, h)。调用方统一走这里，别自己拆长短边（漏传 short_side 会丢短边保底）。"""
    return det_overrides(max(size), scale, short_side=min(size))


def det_overrides(long_side, scale, short_side=None):
    """给 engine.predict() 的 det 覆盖字典；关闭自适应时返回 {}（不覆盖）。

    limit_type="max" 语义为「长边超过 limit 才缩小」，故 scale=1.0 时等价于不缩放。

    ⚠ 短边保底：pipeline 默认的 `64/min` 不只是「不缩小」，它还会把**短边不足 64 的窄图放大**。
    竖排单列裁剪图正是这种极端长条（实测 45×811），放大到 64 宽 det 才能读成一行，
    否则每个字被切成一段。改用 limit_type="max" 会丢掉这层保底，故分三种情形：

      缩放后短边 ≥ 64        → 正常按 scale 缩（limit_type=max）
      缩放后短边 < 64，原短边 ≥ 64 → 把 scale 夹到 64/短边，仍缩小、但短边不破 64
                                  （不能直接交还 64/min：原短边≥64 时它 ratio=1、根本不缩，尺度陷阱复现）
      原短边 < 64            → 交还 `64/min`，让 PaddleX 放大
    """
    if not adaptive_enabled():
        return {}
    if scale and scale > 0:
        short = float(short_side or 0)
        if short and short * float(scale) < MIN_SHORT:
            if short < MIN_SHORT:
                return {"text_det_limit_side_len": MIN_SHORT, "text_det_limit_type": "min"}
            scale = MIN_SHORT / short
        limit = int(round(float(long_side) * float(scale)))
    else:
        limit = int(_num("SHUPAI_DET_LIMIT_SIDE_LEN", FLAT_LIMIT))
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    return {"text_det_limit_side_len": limit, "text_det_limit_type": "max"}
