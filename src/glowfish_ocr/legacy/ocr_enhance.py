# -*- coding: utf-8 -*-
"""满血档的后处理增强层（引擎无关）。

来源：同事分支 onnx-high-accuracy-v2 的「五层优化」。搬进来时做了两处改动：

1. 层⑤（手写页降阈值）原实现是**每页重建一个 PaddleOCR 实例**（`_build_low_thresh_engine`），
   一页一次 912MB 模型加载。这里改成 `engine.predict(..., text_det_box_thresh=0.35)`
   逐调用覆盖——paddleocr 3.x 的 predict() 本来就收 text_det_* 参数。
2. 层④（小字超分）原判据是 `box高 < 20px`。竖排史料里一"行"就是一整列，box 又高又窄，
   该判据几乎永不触发。改成**短边** < 20px，才是"小字"的本意。

每层用环境变量独立关断，供消融：
    GF_HIGH_LOWTHRESH / GF_HIGH_ENSEMBLE / GF_HIGH_SMALLSR / GF_HIGH_MINSCORE
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import ocr_rescue

# 合并前丢弃低于此分的行。**默认 0 = 关闭**：同事原值 0.55，但那是满血档独有的一层
# **减法**，轻量档一行不删，于是淡墨/退化手写页上满血档的召回反而低于轻量档；而且它跑在
# 抢救层之前，被删的行永远等不到超分与多预处理重识。消融实测 ΔF1 = 0.000（五份文档逐一
# 持平），纯亏。保留旋钮供实验。
MIN_LINE_SCORE_DEFAULT = 0.0
# 低置信行走多预处理投票的门槛。
LOW_CONF_THRESH = 0.85
# 集成结果要超过原行多少分才允许替换（同量纲的 rec score）。
ENSEMBLE_REPLACE_MARGIN = 0.05
# 短边小于此像素数的框视作小字，2x 超分重识。
SMALL_TEXT_MIN_SIDE = 20
# 手写页第二趟检测的 box_thresh（正常档 0.45）。
LOW_DET_BOX_THRESH = 0.35

_PREPROCESS_NAMES = ("enhanced", "clahe", "denoise")


def _on(name: str) -> bool:
    return (os.environ.get(name) or "1").strip().lower() not in ("0", "false", "off")


_WARNED = set()


def _warn_once(key: str, message: str) -> None:
    """同一类告警一页只吼一次，免得每个低置信行都刷一遍。"""
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(f"WARN: {message}", file=sys.stderr)


def _min_line_score() -> float:
    """调用时读取，且容错解析。

    以前这里是模块级 `float(os.environ[...])`：GF_HIGH_MINSCORE=off（与另外四个开关同样的
    写法）会让 `import ocr_enhance` 直接抛 ValueError，整个 OCR 子进程起不来；同进程内
    monkeypatch 环境变量做消融时它也纹丝不动，给出「以为关了实则没关」的假数据。
    """
    raw = (os.environ.get("GF_HIGH_MINSCORE") or "").strip().lower()
    if not raw:
        return MIN_LINE_SCORE_DEFAULT
    if raw in ("0", "false", "off", "no"):
        return 0.0
    try:
        return float(raw)
    except ValueError:
        print(f"WARN: GF_HIGH_MINSCORE={raw!r} 不是数字，按默认 {MIN_LINE_SCORE_DEFAULT} 处理",
              file=sys.stderr)
        return MIN_LINE_SCORE_DEFAULT


# ── 层②：多预处理识别集成 ──────────────────────────────────────────────────

def _preprocess_enhanced(img):
    """整页归一化用的同一套增强——直接复用，别再抄一份，免得参数漂移。"""
    return ocr_rescue.enhance_for_ocr(img)


def _preprocess_clahe(img):
    """CLAHE 均衡 + Otsu 二值——对付光照不匀。"""
    import cv2
    import numpy as np
    from PIL import Image
    gray = np.array(img.convert("L"))
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    _, binary = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return Image.fromarray(cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB))


def _preprocess_denoise(img):
    """双边去噪 + gamma——对付纸纹与透印。"""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps
    gray = np.array(img.convert("L"))
    denoised = cv2.bilateralFilter(gray, 9, 75, 75)
    table = np.array([((i / 255.0) ** 1.15) * 255 for i in range(256)]).astype(np.uint8)
    corrected = cv2.LUT(denoised, table)
    return ImageOps.autocontrast(Image.fromarray(corrected), cutoff=1).convert("RGB")


_PREPROCESS_FNS = (_preprocess_enhanced, _preprocess_clahe, _preprocess_denoise)


def _vote_chars(results):
    """按字符位加权投票，返回 (text, agreement)。

    ⚠ agreement 是「几个变体彼此同意」的比例，**不是识别置信度**：三个变体一起把
    某字认错时它照样接近 1.0。绝不可拿它跟模型的 rec score 比大小来决定是否替换
    （同事原实现就这么干，实测把 0.792 的正确行换成 0.953 的错误行）。
    只在各变体等长时调用——按位投票假设对齐，一处多识/漏识就会让其后全部错位。
    """
    lengths = {len(t) for t, _ in results}
    if len(lengths) != 1:
        return None
    voted, agrees = [], []
    for pos in range(lengths.pop()):
        weighted, weight_total = {}, 0.0
        for text, score in results:
            ch = text[pos]
            w = max(0.01, float(score))
            weighted[ch] = weighted.get(ch, 0.0) + w
            weight_total += w
        best = max(weighted, key=weighted.get)
        voted.append(best)
        agrees.append(weighted[best] / max(0.01, weight_total))
    if not voted:
        return None
    return "".join(voted), round(sum(agrees) / len(agrees), 4)


def _multi_preprocess_recognize(predict_crop, crop_image, work_dir, stem):
    """三种预处理各识一遍。返回 (text, score, agreement) 或 None。

    score 一律是**变体识别分的均值**——与模型 rec score 同量纲，可直接与原行比较。
    等长则用投票文本（多数纠正单个变体的偶发错字）；不等长则退回最高分变体，
    避免按位投票错位。
    """
    results = []
    failures = []
    for name, fn in zip(_PREPROCESS_NAMES, _PREPROCESS_FNS):
        path = Path(work_dir) / f"{stem}_{name}.jpg"
        try:
            processed = fn(crop_image)
            processed.save(path, "JPEG", quality=92)
            lines = predict_crop(path, processed.size)
            # 裁剪图被切成多行 = 无法判定哪一行对应原行；只取 lines[0] 会用片段替换整行。
            if len(lines) == 1:
                results.append((lines[0]["text"], float(lines[0].get("score", 0.0))))
        except Exception as exc:
            failures.append(f"{name}: {exc!r}")
            continue
        finally:
            # 每个低置信行落 3 张中间图，不删会堆进用户的 _img 工作目录。
            path.unlink(missing_ok=True)
    if failures:
        # 缺 cv2 时 clahe/denoise 会稳定抛异常，集成层静默退化成空操作。必须出声。
        _warn_once("preprocess_failed", f"多预处理变体失败（集成层降级）：{'; '.join(failures)}")
    if len(results) < 2:
        return None
    mean_score = round(sum(s for _, s in results) / len(results), 4)
    voted = _vote_chars(results)
    if voted is not None:
        return voted[0], mean_score, voted[1]
    best_text, best_score = max(results, key=lambda r: r[1])
    return best_text, mean_score, 0.0


def enhance_low_confidence_lines(predict_crop, lines, oriented, norm_dir, pid):
    """低置信行重识：三预处理投票，赢了才替换。就地改 lines。"""
    if not _on("GF_HIGH_ENSEMBLE"):
        return lines
    for idx, line in enumerate(lines or []):
        if (line.get("score") or 0) >= LOW_CONF_THRESH:
            continue
        try:
            x1, y1, x2, y2 = [int(v) for v in (line.get("box") or [0, 0, 0, 0])[:4]]
            if x2 <= x1 or y2 <= y1:
                continue
            crop = oriented.crop((x1, y1, x2, y2))
            result = _multi_preprocess_recognize(predict_crop, crop, norm_dir, f"{pid}_lc_{idx:03d}")
            if result is None:
                continue
            new_text, new_score, agreement = result
            if not new_text.strip():
                continue
            # 要真的更有把握才换：同量纲的 rec 分 + 一个余量。裁剪重识丢了整页上下文，
            # 平手时原行更可信。
            if new_score > (line.get("score") or 0) + ENSEMBLE_REPLACE_MARGIN:
                line["text"] = new_text
                line["score"] = new_score
                line["ensemble_sources"] = list(_PREPROCESS_NAMES)
                line["ensemble_agreement"] = agreement
        except Exception:
            continue
    return lines


# ── 层④：小字超分重识 ────────────────────────────────────────────────────

def rescue_small_text(predict_crop, lines, oriented, norm_dir, pid):
    """短边 <20px 的框放大 2x（Lanczos）重识，更长或更高分才替换。就地改 lines。"""
    if not _on("GF_HIGH_SMALLSR"):
        return lines
    from PIL import Image
    for idx, line in enumerate(lines or []):
        try:
            x1, y1, x2, y2 = [int(v) for v in (line.get("box") or [0, 0, 0, 0])[:4]]
            if x2 <= x1 or y2 <= y1:
                continue
            if min(x2 - x1, y2 - y1) >= SMALL_TEXT_MIN_SIDE:
                continue
            crop = oriented.crop((x1, y1, x2, y2))
            w, h = crop.size
            if w < 2 or h < 2:
                continue
            upscaled = crop.resize((w * 2, h * 2), Image.LANCZOS)
            path = Path(norm_dir) / f"{pid}_small_{idx:03d}.jpg"
            upscaled.save(path, "JPEG", quality=92)
            try:
                new_lines = predict_crop(path, upscaled.size)
            finally:
                path.unlink(missing_ok=True)
            # 放大后检测器常把一个短列切成数段。原实现取分最高的那一段替换整行——
            # 单字段的置信度天然高于多字段，于是「壹佰兩」(0.80) 会被换成「壹」(0.93)，静默丢字。
            # 切成多段 = 无法确定哪段对应原行，直接放弃这次抢救。
            if len(new_lines) != 1:
                continue
            best = new_lines[0]
            old_text = str(line.get("text", "")).strip()
            new_text = str(best.get("text", "")).strip()
            if not new_text or len(new_text) < len(old_text):
                continue          # 绝不用更短的结果覆盖：宁可保留原文，也不丢字
            if len(new_text) > len(old_text) or best.get("score", 0) > (line.get("score") or 0) + 0.05:
                line["text"] = new_text
                line["score"] = best.get("score", line.get("score"))
                line["small_rescue"] = True
        except Exception:
            continue
    return lines


# ── 层⑤：手写页自适应降阈值 ──────────────────────────────────────────────

def looks_like_handwriting(lines, width, height):
    """稀疏 / 小字 / 低墨占比的页面，值得再用低 box_thresh 检一遍。"""
    if not lines:
        return True
    if len(lines) < 12 and max(width, height) > 800:
        return True
    heights = [b[3] - b[1] for b in (l.get("box") or [0, 0, 0, 0] for l in lines) if b[3] - b[1] > 0]
    if heights and sum(heights) / len(heights) < 35:
        return True
    box_area = 0.0
    for line in lines:
        b = line.get("box") or [0, 0, 0, 0]
        box_area += max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return box_area / max(1.0, float(width) * float(height)) < 0.12


def low_thresh_enabled():
    """**默认关**。判据 `len(lines)<12 and max(w,h)>800` 在竖排史料上几乎恒真——整页只检出
    十来条「列」级行，长边动辄数千像素。实测 bench 手写集 11 页中 6 页触发，每次多跑一整趟
    整页 detect+rec（神经网络推理约占单页耗时 41%），而消融 F1 五份文档逐一持平（Δ=0.000）。
    想开就设 GF_HIGH_LOWTHRESH=1。
    """
    return (os.environ.get("GF_HIGH_LOWTHRESH") or "0").strip().lower() not in ("0", "false", "off")


def low_thresh_det(det):
    """在既有 det 覆盖（自适应尺度）之上叠加低 box_thresh，尺度与阈值正交。"""
    out = dict(det or {})
    out["text_det_box_thresh"] = LOW_DET_BOX_THRESH
    return out


# ── 合并前的低分预过滤 ───────────────────────────────────────────────────

def prefilter_by_score(lines):
    threshold = _min_line_score()
    if threshold <= 0:
        return list(lines or [])
    return [l for l in (lines or []) if (l.get("score") or 0) >= threshold]


def quality_summary(lines):
    total = len(lines or [])
    chars = sum(len(str(l.get("text", "")).strip()) for l in lines or [])
    score_sum, scored, sources = 0.0, 0, {}
    for line in lines or []:
        key = line.get("source") or ""
        sources[key] = sources.get(key, 0) + 1
        try:
            score_sum += float(line.get("score", 0.0))
            scored += 1
        except Exception:
            pass
    return {"lines": total, "chars": chars,
            "avg_score": score_sum / scored if scored else 0.0, "sources": sources}
