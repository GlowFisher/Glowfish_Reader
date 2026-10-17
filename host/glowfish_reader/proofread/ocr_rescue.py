# -*- coding: utf-8 -*-
"""Page-level OCR rescue helpers for historical vertical documents.

The helpers are intentionally model-agnostic: they inspect page geometry and OCR
line contracts, then decide whether to try column-level OCR or engine fallback.
They never delete OCR text.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


Box = Tuple[int, int, int, int]


@dataclass(frozen=True)
class RecallStats:
    lines: int
    chars: int
    area_ratio: float


def _line_chars(lines: Iterable[dict]) -> int:
    return sum(len(str(line.get("text", "")).strip()) for line in lines or [])


def recall_stats(lines: Sequence[dict], width: int, height: int) -> RecallStats:
    page_area = max(1.0, float(width or 1) * float(height or 1))
    area = 0.0
    for line in lines or []:
        try:
            x1, y1, x2, y2 = [float(v) for v in (line.get("box") or [0, 0, 0, 0])[:4]]
        except Exception:
            continue
        area += max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return RecallStats(lines=len(lines or []), chars=_line_chars(lines), area_ratio=area / page_area)


def is_low_recall(lines: Sequence[dict], width: int, height: int) -> bool:
    stats = recall_stats(lines, width, height)
    if stats.lines == 0:
        return True
    if stats.chars < 80 and stats.area_ratio < 0.18:
        return True
    if stats.lines <= 2 and stats.chars < 120:
        return True
    return False


def enhance_for_ocr(image):
    """Return a same-size contrast-enhanced RGB image for OCR only."""
    from PIL import ImageEnhance, ImageFilter, ImageOps

    rgb = image.convert("RGB")
    gray = ImageOps.grayscale(rgb)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.35)
    gray = gray.filter(ImageFilter.SHARPEN)
    return ImageOps.colorize(gray, black="#111111", white="#ffffff").convert("RGB")


def find_body_region(image, pad_ratio: float = 0.04) -> Box:
    """Find the dense paper/text region, ignoring large uniform background."""
    import numpy as np

    gray = np.asarray(image.convert("L"))
    # Historical pages here usually have dark ink on light paper/background.
    dark = gray < min(210, max(80, int(gray.mean() - gray.std() * 0.15)))
    ys, xs = np.where(dark)
    w, h = image.size
    if len(xs) < 20 or len(ys) < 20:
        return (0, 0, w, h)
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    pad = int(max(w, h) * pad_ratio)
    return (max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad))


def _merge_spans(spans: List[Tuple[int, int]], gap: int) -> List[Tuple[int, int]]:
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for a, b in spans[1:]:
        la, lb = merged[-1]
        if a <= lb + gap:
            merged[-1] = (la, max(lb, b))
        else:
            merged.append((a, b))
    return merged


def _strip_frame_rules(dark):
    """置零"整行/整列几乎全黑"的像素带——史料页的粗黑边框(如退想斋影印本)。

    边框实心竖条的暗占比≈1.0，正文竖列约 0.3~0.5，0.7 阈值不会误伤文字列。
    不去掉的话上下横条会让每个 x 都"活跃"，投影分列直接失效。
    """
    import numpy as np

    out = dark.copy()
    if out.size == 0:
        return out
    col_frac = out.mean(axis=0)
    row_frac = out.mean(axis=1)
    out[:, col_frac > 0.70] = False
    out[row_frac > 0.70, :] = False
    return out


def _estimate_pitch(profile, width):
    """用自相关估竖排列间距（像素）。找不到稳定周期返回 0。

    两处要点：① 先平滑掉笔画级细纹，否则自相关会锁到笔画周期（实测日记 90px，
    真实列距 ~350px）；② 搜索范围限定在"整页 8~30 列"这个版式常识带内。
    """
    import numpy as np

    p = _smooth(np.asarray(profile), max(3, width // 200))
    p = p - p.mean()
    if not np.any(p):
        return 0
    lo, hi = max(8, width // 30), max(12, width // 7)
    if hi <= lo or hi >= len(p):
        return 0
    ac = np.correlate(p, p, mode="full")[len(p) - 1:]
    seg = ac[lo:hi]
    if seg.size == 0 or not np.any(seg > 0):
        return 0
    return int(lo + int(np.argmax(seg)))


def _smooth(profile, win):
    import numpy as np
    win = max(1, int(win) | 1)
    if win <= 1:
        return profile.astype(np.float64)
    kern = np.ones(win) / win
    return np.convolve(profile.astype(np.float64), kern, mode="same")


def _split_span_by_valleys(col_counts, a, b, pitch):
    """把一个宽 span 按投影波谷切成多列（行草粘连时 gap 合并法救不回来）。"""
    import numpy as np

    seg = col_counts[a:b]
    if pitch <= 0 or seg.size < pitch * 1.6:
        return [(a, b)]
    sm = _smooth(seg, max(3, pitch // 6))
    med = float(np.median(sm[sm > 0])) if np.any(sm > 0) else 0.0
    if med <= 0:
        return [(a, b)]
    min_sep = max(4, int(pitch * 0.6))
    cuts = []
    i = min_sep
    while i < len(sm) - min_sep:
        window = sm[max(0, i - min_sep // 2): i + min_sep // 2 + 1]
        if sm[i] <= window.min() and sm[i] < med * 0.60:
            if not cuts or (i - cuts[-1]) >= min_sep:
                cuts.append(i)
            i += min_sep
        else:
            i += 1
    if not cuts:
        return [(a, b)]
    spans, prev = [], 0
    for c in cuts:
        spans.append((a + prev, a + c))
        prev = c
    spans.append((a + prev, b))
    # 过窄碎片(<0.6 列距)不是真列，留着会让 aggregate_columns 读序错乱——并回邻列。
    min_w = max(4, int(pitch * 0.60))
    out: List[Tuple[int, int]] = []
    for s, e in spans:
        if e - s >= min_w:
            out.append((s, e))
        elif out:
            out[-1] = (out[-1][0], e)     # 并入左邻
        elif len(spans) > 1:
            continue                      # 首个碎片直接丢
    return out or [(a, b)]


def _column_detect_v2_enabled() -> bool:
    return os.environ.get("SHUPAI_COL_DETECT_V2", "1").strip().lower() not in ("0", "false", "no", "")


def find_vertical_text_columns(image, max_columns: int = 24) -> List[Box]:
    """Detect likely vertical text columns by dark-pixel projection.

    This is a recall-oriented rescue detector. It may produce extra candidate
    columns, but later noise classification keeps those out of the editable text.
    """
    import numpy as np

    x1, y1, x2, y2 = find_body_region(image)
    crop = image.crop((x1, y1, x2, y2)).convert("L")
    arr = np.asarray(crop)
    if arr.size == 0:
        return []
    # Use a local threshold so faded ink on blue/aged background still counts.
    thresh = min(190, max(95, int(arr.mean() - arr.std() * 0.25)))
    dark = arr < thresh
    v2 = _column_detect_v2_enabled()
    if v2:
        dark = _strip_frame_rules(dark)      # 粗黑边框会让每个 x 都"活跃"，先抹掉
    col_counts = dark.sum(axis=0)
    h, w = dark.shape
    min_pixels = max(4, int(h * 0.025))
    active = col_counts >= min_pixels
    spans = []
    start = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(active)))
    spans = _merge_spans(spans, gap=max(3, int(w * 0.012)))
    if v2:
        # 行草横向粘连时上面会并出一个跨整幅的 span → 按投影波谷再切开。
        pitch = _estimate_pitch(col_counts, w)
        if pitch > 0:
            split: List[Tuple[int, int]] = []
            for a, b in spans:
                split.extend(_split_span_by_valleys(col_counts, a, b, pitch))
            if split:
                spans = split
    boxes: List[Box] = []
    min_w = max(4, int(w * 0.008))
    for a, b in spans:
        if b - a < min_w:
            continue
        strip = dark[:, a:b]
        ys = np.where(strip.any(axis=1))[0]
        if len(ys) < max(12, int(h * 0.08)):
            continue
        pad_x = max(4, int((b - a) * 0.35))
        pad_y = max(8, int(h * 0.025))
        boxes.append((max(0, x1 + a - pad_x), max(0, y1 + int(ys.min()) - pad_y),
                      min(image.width, x1 + b + pad_x), min(image.height, y1 + int(ys.max()) + 1 + pad_y)))
    # Right-to-left reading order, and cap runaway detections.
    boxes = sorted(boxes, key=lambda b: -((b[0] + b[2]) / 2.0))
    return boxes[:max_columns]


def uncovered_columns(columns: Sequence[Box], lines: Sequence[dict], min_overlap: float = 0.25) -> List[Box]:
    """Return candidate columns that are not covered by existing OCR boxes."""
    missing: List[Box] = []
    for col in columns or []:
        cx1, cy1, cx2, cy2 = [float(v) for v in col]
        cw = max(1.0, cx2 - cx1)
        ch = max(1.0, cy2 - cy1)
        covered = False
        for line in lines or []:
            try:
                lx1, ly1, lx2, ly2 = [float(v) for v in (line.get("box") or [0, 0, 0, 0])[:4]]
            except Exception:
                continue
            x_overlap = max(0.0, min(cx2, lx2) - max(cx1, lx1)) / cw
            y_overlap = max(0.0, min(cy2, ly2) - max(cy1, ly1)) / ch
            if x_overlap >= min_overlap and y_overlap >= 0.35:
                covered = True
                break
        if not covered:
            missing.append(col)
    return missing

# --- 选择性列重识别（S2）：只对"没救到/救得差"的列重跑，别无差别全列双跑 -------------
# high_accuracy 旧行为=每列跑 column_rescue + column_wide_rescue 两趟全尺度 det+rec，
# 一页 ~28 趟 → 22 分钟。绝大多数列 full_enhanced 已经识别得很好，重跑纯属浪费。
# 下面的判据只看"这列现有识别结果够不够好"，不确定就救（宁慢勿错）。


def _cfg(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return float(default)


def map_crop_line(line: dict, offset: Box, source: str) -> dict:
    ox, oy, _, _ = offset
    out = dict(line)
    try:
        x1, y1, x2, y2 = [float(v) for v in (line.get("box") or [0, 0, 0, 0])[:4]]
        out["box"] = [x1 + ox, y1 + oy, x2 + ox, y2 + oy]
    except Exception:
        out["box"] = [float(ox), float(oy), float(ox + 1), float(oy + 1)]
    out["source"] = source
    return out


def merge_high_accuracy_lines(lines: Sequence[dict]) -> tuple[List[dict], dict]:
    kept: List[dict] = []
    duplicates_removed = 0
    garbage_rejected = 0
    for line in lines or []:
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        duplicate = False
        for idx, old in enumerate(kept):
            if not _is_high_accuracy_duplicate(line, old):
                continue
            duplicate = True
            preferred = _prefer_high_accuracy_line(line, old)
            if preferred is not line and _looks_like_garbage_text_column(line):
                garbage_rejected += 1
            if preferred is not old:
                kept[idx] = line
                if _looks_like_garbage_text_column(old):
                    garbage_rejected += 1
            duplicates_removed += 1
            break
        if not duplicate:
            kept.append(line)
    return kept, {
        "input_lines": len(lines or []),
        "output_lines": len(kept),
        "duplicates_removed": duplicates_removed,
        "garbage_rejected": garbage_rejected,
    }


def _is_high_accuracy_duplicate(line: dict, old: dict) -> bool:
    if _iou(line.get("box"), old.get("box")) >= 0.68:
        return True
    if _looks_like_vertical_column(line) and _looks_like_vertical_column(old):
        if _vertical_column_overlap(line.get("box"), old.get("box")) >= 0.80:
            return True
    # 2a：不同候选源、同列 y 被包含的碎片（短行是长行的子串/高相似）也判重。
    # 落款「中华民国…」在 full_enhanced/column_rescue/column_wide_rescue 里被切成多段、
    # 裁切框差异大 → IoU 漏判 → aggregate_columns 拼出「中中华中华民国…」重复串。
    if _fragment_dedup_enabled() and _different_source(line, old):
        if _contain_ratio(line.get("box"), old.get("box")) >= 0.5 and _fragment_similar(
            str(line.get("text", "")).strip(), str(old.get("text", "")).strip()
        ):
            return True
    return False


def _fragment_dedup_enabled() -> bool:
    return os.environ.get("SHUPAI_FRAGMENT_DEDUP", "1").strip().lower() not in ("0", "false", "no", "")


def _different_source(a: dict, b: dict) -> bool:
    sa, sb = str(a.get("source", "")), str(b.get("source", ""))
    return bool(sa) and bool(sb) and sa != sb


def _contain_ratio(a, b) -> float:
    """交叠面积占较小框面积的比例（衡量“小框被大框包含”的程度）。"""
    try:
        ax1, ay1, ax2, ay2 = [float(v) for v in a[:4]]
        bx1, by1, bx2, by2 = [float(v) for v in b[:4]]
    except Exception:
        return 0.0
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    if inter <= 0:
        return 0.0
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1.0, min(aa, ba))


def _norm_edit_sim(a: str, b: str) -> float:
    la, lb = len(a), len(b)
    if la == 0 and lb == 0:
        return 1.0
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        for j in range(1, lb + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if ai == b[j - 1] else 1))
        prev = cur
    return 1.0 - prev[lb] / max(la, lb)


def _fragment_similar(a: str, b: str) -> bool:
    """短行是长行的连续子串（碎片），或整体归一化编辑相似度≥0.7（错字碎片）。"""
    if not a or not b:
        return False
    short, lng = (a, b) if len(a) <= len(b) else (b, a)
    if short in lng:
        return True
    return _norm_edit_sim(a, b) >= 0.7


def _prefer_high_accuracy_line(candidate: dict, current: dict) -> dict:
    cand_garbage = _looks_like_garbage_text_column(candidate)
    cur_garbage = _looks_like_garbage_text_column(current)
    if cand_garbage != cur_garbage:
        return current if cand_garbage else candidate
    cand_len = len(str(candidate.get("text", "")).strip())
    cur_len = len(str(current.get("text", "")).strip())
    cand_score = _line_score(candidate)
    cur_score = _line_score(current)
    if cand_len > cur_len and cand_score >= cur_score - 0.08:
        return candidate
    if cur_len > cand_len and cur_score >= cand_score - 0.08:
        return current
    return candidate if (cand_score, cand_len) > (cur_score, cur_len) else current


def _looks_like_garbage_text_column(line: dict) -> bool:
    text = str(line.get("text", "")).strip()
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    if len(cjk) < 8 or not _looks_like_vertical_column(line):
        return False
    counts = {}
    for ch in cjk:
        counts[ch] = counts.get(ch, 0) + 1
    repeated_ratio = max(counts.values()) / max(1, len(cjk))
    unique_ratio = len(counts) / max(1, len(cjk))
    garbage_chars = set("\u623f\u52a1\u5802\u5e02")
    garbage_ratio = sum(1 for ch in cjk if ch in garbage_chars) / max(1, len(cjk))
    return _line_score(line) < 0.72 and (
        repeated_ratio >= 0.28 or unique_ratio <= 0.35 or garbage_ratio >= 0.35
    )

def dedupe_lines(lines: Sequence[dict], iou_threshold: float = 0.72) -> List[dict]:
    kept: List[dict] = []
    for line in lines or []:
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        duplicate = False
        for idx, old in enumerate(kept):
            if _is_duplicate_line(line, old, iou_threshold):
                duplicate = True
                if _prefer_line(line, old) is line:
                    kept[idx] = line
                break
        if not duplicate:
            kept.append(line)
    return kept


def _is_duplicate_line(line: dict, old: dict, iou_threshold: float) -> bool:
    text = str(line.get("text", "")).strip()
    old_text = str(old.get("text", "")).strip()
    if text == old_text and _iou(line.get("box"), old.get("box")) >= iou_threshold:
        return True
    if not _is_auto_rescue_pair(line, old):
        return False
    if not (_looks_like_vertical_column(line) and _looks_like_vertical_column(old)):
        return False
    return _vertical_column_overlap(line.get("box"), old.get("box")) >= 0.82


def _is_auto_rescue_pair(a: dict, b: dict) -> bool:
    return {a.get("source"), b.get("source")} == {"full_page", "column_rescue"}


def _looks_like_vertical_column(line: dict) -> bool:
    try:
        x1, y1, x2, y2 = [float(v) for v in (line.get("box") or [])[:4]]
    except Exception:
        return False
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    text_len = len(str(line.get("text", "")).strip())
    return height >= max(80.0, width * 3.0) and text_len >= 6


def _vertical_column_overlap(a, b) -> float:
    try:
        ax1, ay1, ax2, ay2 = [float(v) for v in a[:4]]
        bx1, by1, bx2, by2 = [float(v) for v in b[:4]]
    except Exception:
        return 0.0
    x_inter = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    y_inter = max(0.0, min(ay2, by2) - max(ay1, by1))
    min_w = max(1.0, min(abs(ax2 - ax1), abs(bx2 - bx1)))
    min_h = max(1.0, min(abs(ay2 - ay1), abs(by2 - by1)))
    return min(x_inter / min_w, y_inter / min_h)


def _prefer_line(candidate: dict, current: dict) -> dict:
    cand_source = candidate.get("source")
    cur_source = current.get("source")
    if cand_source == "column_rescue" and cur_source == "full_page":
        return current if _full_page_clearly_better(current, candidate) else candidate
    if cand_source == "full_page" and cur_source == "column_rescue":
        return candidate if _full_page_clearly_better(candidate, current) else current
    return candidate if _line_quality(candidate) > _line_quality(current) else current


def _full_page_clearly_better(full_page: dict, column_rescue: dict) -> bool:
    full_len = len(str(full_page.get("text", "")).strip())
    rescue_len = len(str(column_rescue.get("text", "")).strip())
    full_score = _line_score(full_page)
    rescue_score = _line_score(column_rescue)
    return full_len >= rescue_len + 6 or full_score >= rescue_score + 0.08


def _line_quality(line: dict) -> tuple:
    return (len(str(line.get("text", "")).strip()), _line_score(line))


def _line_score(line: dict) -> float:
    try:
        return float(line.get("score", 0.0))
    except Exception:
        return 0.0


def _iou(a, b) -> float:
    try:
        ax1, ay1, ax2, ay2 = [float(v) for v in a[:4]]
        bx1, by1, bx2, by2 = [float(v) for v in b[:4]]
    except Exception:
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    ba = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1.0, aa + ba - inter)

