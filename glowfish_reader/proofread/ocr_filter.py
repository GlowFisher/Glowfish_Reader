# -*- coding: utf-8 -*-
"""Conservative post-OCR filters for non-body text.

The OCR contract stays unchanged: callers pass lines with text/box/score and get
back the kept subset. The rules combine text, geometry, confidence, and optional
image-color evidence so seals and page-edge catalog marks are filtered even when
OCR turns them into ordinary-looking Chinese.
"""
import re
import unicodedata
from pathlib import Path

WATERMARK_RE = re.compile(
    r"(cam\s*scanner|camscanner|scan(ned)?\s+by|water\s*mark|watermark|"
    r"sample|copyright|confidential|www\.|https?://|@[a-z0-9.-]+\.)",
    re.I,
)
SEAL_TERMS = ("印", "章", "鈐", "钤", "璽", "玺", "藏書", "藏书")
CENTER_MARK_TERMS = ("目录", "目錄", "版心", "页心", "頁心")
SIDE_CATALOG_TERMS = ("宗譜", "宗谱", "族譜", "族谱", "譜", "谱")


def _clean_text(text):
    return "".join(ch for ch in str(text or "").strip() if unicodedata.category(ch)[0] != "C")


def _box(line):
    vals = line.get("box") or [0, 0, 0, 0]
    try:
        x1, y1, x2, y2 = [float(v) for v in vals[:4]]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def _score(line):
    try:
        return float(line.get("score", 1.0))
    except Exception:
        return 1.0


def _ascii_ratio(text):
    chars = [ch for ch in text if not ch.isspace()]
    if not chars:
        return 0.0
    return sum(1 for ch in chars if ord(ch) < 128) / len(chars)


def _metrics(line, page_w, page_h):
    x1, y1, x2, y2 = _box(line)
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    pw = max(1.0, float(page_w or 1))
    ph = max(1.0, float(page_h or 1))
    cx_ratio = ((x1 + x2) / 2.0) / pw
    cy_ratio = ((y1 + y2) / 2.0) / ph
    return {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "w": w, "h": h, "area_ratio": (w * h) / (pw * ph),
        "cx_ratio": cx_ratio, "cy_ratio": cy_ratio,
        "w_ratio": w / pw, "h_ratio": h / ph,
        "near_margin": x1 <= pw * 0.15 or x2 >= pw * 0.85 or y1 <= ph * 0.08 or y2 >= ph * 0.92,
        "extreme_side": cx_ratio <= 0.14 or cx_ratio >= 0.84,
    }


def _looks_like_watermark(text, m):
    if _ascii_ratio(text) < 0.72:
        return False
    if WATERMARK_RE.search(text):
        return True
    return m["w_ratio"] >= 0.45 and m["h_ratio"] <= 0.08


def _looks_like_ascii_noise(text, m, score):
    return _ascii_ratio(text) >= 0.55 and len(text) <= 10 and (score < 0.85 or m["near_margin"])


def _looks_like_seal(text, m):
    if not any(term in text for term in SEAL_TERMS):
        return False
    return len(text) <= 8 and (m["area_ratio"] <= 0.035 or m["near_margin"])


def _looks_like_center_mark(text, m):
    if len(text) > 8:
        return False
    near_centerline = abs(m["cx_ratio"] - 0.5) <= 0.06
    narrow = m["w_ratio"] <= 0.08
    short = m["h_ratio"] <= 0.18
    has_marker_text = any(term in text for term in CENTER_MARK_TERMS) or re.fullmatch(r"[一二三四五六七八九十百千\d第卷册頁页目录目錄\-—]+", text)
    return near_centerline and narrow and short and bool(has_marker_text)


def _looks_like_side_catalog(text, m, score):
    if not m["extreme_side"] or m["h_ratio"] > 0.18 or m["w_ratio"] > 0.05:
        return False
    return len(text) <= 8 and (score < 0.8 or any(term in text for term in SIDE_CATALOG_TERMS) or _ascii_ratio(text) >= 0.4)


def _looks_like_body_column(text, m):
    cjk = sum(1 for ch in text if ord(ch) > 127)
    cjk_ratio = cjk / max(1, len([ch for ch in text if not ch.isspace()]))
    return cjk_ratio >= 0.65 and m["h_ratio"] >= 0.22 and m["w_ratio"] <= 0.14 and len(text) >= 6


def _looks_like_low_conf_noise(text, m, score):
    if score >= 0.55:
        return False
    if _looks_like_body_column(text, m):
        return False
    return len(text) <= 12 or (m["near_margin"] and len(text) <= 30) or (m["w_ratio"] <= 0.035 and len(text) <= 10)


def _image_ratios(image, line):
    if image is None:
        return {"red": 0.0, "pale_red": 0.0}
    try:
        x1, y1, x2, y2 = [int(round(v)) for v in _box(line)]
        x1 = max(0, min(image.width, x1)); x2 = max(0, min(image.width, x2))
        y1 = max(0, min(image.height, y1)); y2 = max(0, min(image.height, y2))
        if x2 <= x1 or y2 <= y1:
            return {"red": 0.0, "pale_red": 0.0}
        crop = image.crop((x1, y1, x2, y2)).convert("RGB")
        if hasattr(crop, "get_flattened_data"):
            pixels = list(crop.get_flattened_data())
        else:
            pixels = list(crop.getdata())
    except Exception:
        return {"red": 0.0, "pale_red": 0.0}
    if not pixels:
        return {"red": 0.0, "pale_red": 0.0}
    n = len(pixels)
    red = sum(1 for r, g, b in pixels if r > g + 25 and r > b + 25 and r > 80) / n
    pale = sum(1 for r, g, b in pixels if r > g + 10 and r > b + 10 and r > 120) / n
    return {"red": red, "pale_red": pale}


def _looks_like_colored_stamp(text, m, score, ratios):
    if ratios["pale_red"] < 0.25 and ratios["red"] < 0.12:
        return False
    if _looks_like_body_column(text, m) and not any(term in text for term in SEAL_TERMS):
        return False
    if any(term in text for term in SEAL_TERMS):
        return len(text) <= 10 or m["near_margin"]
    return len(text) <= 6 and (score < 0.85 or m["near_margin"])


def _open_image(image_path):
    if not image_path:
        return None
    try:
        from PIL import Image
        return Image.open(Path(image_path)).convert("RGB")
    except Exception:
        return None


def classify_line(line, page_w, page_h, image=None):
    """Return (status, reason) without deleting OCR output.

    status is "main_text" or "noise". Reasons are intentionally stable enough
    for UI/debug display but conservative enough to keep the old filter usable.
    """
    text = _clean_text(line.get("text", ""))
    if not text:
        return "noise", "empty"
    m = _metrics(line, page_w, page_h)
    score = _score(line)
    ratios = _image_ratios(image, line)
    checks = [
        ("watermark", _looks_like_watermark(text, m)),
        ("ascii_noise", _looks_like_ascii_noise(text, m, score)),
        ("seal", _looks_like_seal(text, m)),
        ("page_center", _looks_like_center_mark(text, m)),
        ("side_catalog", _looks_like_side_catalog(text, m, score)),
        ("low_conf_noise", _looks_like_low_conf_noise(text, m, score)),
        ("colored_stamp", _looks_like_colored_stamp(text, m, score, ratios)),
    ]
    for reason, matched in checks:
        if matched:
            return "noise", reason
    return "main_text", ""


def annotate_page_lines(lines, width, height, image_path=None):
    image = _open_image(image_path)
    annotated = []
    for line in (lines or []):
        out = dict(line)
        status, reason = classify_line(out, width, height, image=image)
        out["filter_status"] = status
        out["filter_reason"] = reason
        annotated.append(out)
    return annotated


def filter_page_lines(lines, width, height, image_path=None):
    return [line for line in annotate_page_lines(lines, width, height, image_path)
            if line.get("filter_status") != "noise"]





