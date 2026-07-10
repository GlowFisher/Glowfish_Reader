# -*- coding: utf-8 -*-
"""迭代2a 回归：high_accuracy 候选合并的碎片判重（落款「中华民国」重复最小复现）。

fixture 取自 s03 盐号公文 p2 落款列真实 recog 碎片（同一物理竖列被切成多段、
不同候选源、裁切框差异大 → 旧 IoU 判重漏判 → aggregate_columns 拼出重复串）。
"""
import os

import numpy as np
from PIL import Image

import ocr_rescue


# 真实落款碎片：中華民國三 / 中 / 民國 / 氏國三（同列 y 重叠）+ 年七月 / 年七 / 月
_LAKUAN = [
    {"text": "中華民國三", "box": [638, 29, 944, 2122], "score": 0.99, "source": "full_enhanced"},
    {"text": "中", "box": [669, 42, 930, 535], "score": 0.84, "source": "column_rescue"},
    {"text": "民國", "box": [663, 886, 956, 1627], "score": 0.95, "source": "column_rescue"},
    {"text": "氏國三", "box": [624, 877, 980, 1941], "score": 0.88, "source": "column_wide_rescue"},
    {"text": "年七月", "box": [627, 2760, 986, 3877], "score": 1.0, "source": "full_enhanced"},
    {"text": "年七", "box": [663, 2747, 956, 3457], "score": 0.97, "source": "column_rescue"},
    {"text": "月", "box": [677, 3401, 916, 3829], "score": 0.5, "source": "column_wide_rescue"},
]


def test_lakuan_fragments_dedup_keeps_zhonghuaminguo_once():
    kept, stats = ocr_rescue.merge_high_accuracy_lines(_LAKUAN)
    texts = [l["text"] for l in kept]
    joined = "".join(texts)
    assert joined.count("中華民國") == 1, texts          # 不再重复
    assert "中" not in texts                              # 单字碎片并入长行
    assert "民國" not in texts
    assert "年七" not in texts                            # 并入「年七月」
    assert "中華民國三" in texts and "年七月" in texts
    assert stats["duplicates_removed"] >= 3


def test_fragment_dedup_only_across_different_sources():
    """同源、文本相似但几何仅轻含的行不因 2a 判重（防吞同候选内真实重复套语）。"""
    same_src = [
        {"text": "中華民國", "box": [640, 30, 940, 900], "score": 0.9, "source": "full_enhanced"},
        {"text": "中華", "box": [660, 40, 900, 480], "score": 0.8, "source": "full_enhanced"},   # 同源
    ]
    kept, _ = ocr_rescue.merge_high_accuracy_lines(same_src)
    assert len(kept) == 2                                 # 同源不走 2a 碎片判重


def test_fragment_dedup_disabled_env():
    old = os.environ.get("SHUPAI_FRAGMENT_DEDUP")
    os.environ["SHUPAI_FRAGMENT_DEDUP"] = "0"
    try:
        kept, _ = ocr_rescue.merge_high_accuracy_lines(_LAKUAN)
        assert "中" in [l["text"] for l in kept]           # 关闭后碎片不并
    finally:
        if old is None:
            os.environ.pop("SHUPAI_FRAGMENT_DEDUP", None)
        else:
            os.environ["SHUPAI_FRAGMENT_DEDUP"] = old
