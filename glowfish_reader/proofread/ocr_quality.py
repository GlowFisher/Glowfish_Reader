# -*- coding: utf-8 -*-
"""Quality signals for choosing between OCR engine outputs."""

from collections import Counter

import ocr_rescue


_CJK_MIN = "\u4e00"
_CJK_MAX = "\u9fff"
_COMMON_GARBAGE_CHARS = set("\u623f\u52a1\u5802\u5e02")


def _is_cjk(ch):
    return _CJK_MIN <= ch <= _CJK_MAX


def _line_text(line):
    return str(line.get("text", "")).strip()


def _line_score(line):
    try:
        return float(line.get("score", 1.0))
    except Exception:
        return 1.0


def _is_tall_line(line):
    try:
        x1, y1, x2, y2 = [float(v) for v in line.get("box", [])[:4]]
    except Exception:
        return False
    width = max(1.0, abs(x2 - x1))
    height = max(1.0, abs(y2 - y1))
    return height >= width * 3.0 and height >= 120.0


def _looks_like_garbage_column(line):
    text = _line_text(line)
    cjk = [ch for ch in text if _is_cjk(ch)]
    if len(cjk) < 8 or not _is_tall_line(line):
        return False
    counts = Counter(cjk)
    repeated_ratio = counts.most_common(1)[0][1] / max(1, len(cjk))
    unique_ratio = len(counts) / max(1, len(cjk))
    garbage_ratio = sum(1 for ch in cjk if ch in _COMMON_GARBAGE_CHARS) / max(1, len(cjk))
    low_score = _line_score(line) < 0.72
    return low_score and (
        repeated_ratio >= 0.28
        or unique_ratio <= 0.35
        or garbage_ratio >= 0.35
    )


def summarize_recog(data):
    """Return aggregate quality metrics for a _recog.json-style object."""
    pages = (page for key, page in data.items() if not str(key).startswith("_")) if isinstance(data, dict) else []
    lines_count = 0
    chars = 0
    main_chars = 0
    low_pages = 0
    score_sum = 0.0
    scored_lines = 0
    suspect_garbage_chars = 0
    noise_chars = 0

    for page in pages:
        if not isinstance(page, dict):
            continue
        lines = page.get("lines", []) or []
        width, height = page.get("width", 0), page.get("height", 0)
        lines_count += len(lines)
        if ocr_rescue.is_low_recall(lines, width, height):
            low_pages += 1
        for line in lines:
            if not isinstance(line, dict):
                continue
            text = _line_text(line)
            text_len = len(text)
            chars += text_len
            score_sum += _line_score(line)
            scored_lines += 1
            if line.get("noise") or line.get("kind") == "noise" or line.get("filter_status") == "noise":
                noise_chars += text_len
            elif line.get("filter_status") in (None, "", "main_text"):
                main_chars += text_len
            if _looks_like_garbage_column(line):
                suspect_garbage_chars += text_len

    avg_score = score_sum / scored_lines if scored_lines else 0.0
    usable_chars = max(0, chars - noise_chars - suspect_garbage_chars)
    return {
        "lines": lines_count,
        "chars": chars,
        "main_chars": main_chars,
        "low_pages": low_pages,
        "noise_chars": noise_chars,
        "suspect_garbage_chars": suspect_garbage_chars,
        "usable_chars": usable_chars,
        "avg_score": avg_score,
    }


def is_better(candidate, current):
    """Return True when candidate is meaningfully better than current."""
    cand = summarize_recog(candidate)
    cur = summarize_recog(current)
    if cand["low_pages"] < cur["low_pages"] and cand["usable_chars"] >= cur["usable_chars"]:
        return True
    if cur["chars"] == 0 and cand["chars"] > 0:
        return True
    if cur["suspect_garbage_chars"] >= 24:
        less_garbage = cand["suspect_garbage_chars"] <= max(8, cur["suspect_garbage_chars"] // 3)
        more_usable = cand["usable_chars"] >= max(80, int(cur["usable_chars"] * 1.15))
        if less_garbage and more_usable:
            return True
    return cand["usable_chars"] >= max(120, int(cur["usable_chars"] * 1.45))
