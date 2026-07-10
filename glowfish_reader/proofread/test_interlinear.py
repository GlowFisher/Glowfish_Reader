# -*- coding: utf-8 -*-
"""迭代1 单测：双行夹注检测/配对/合成 + 全链读序（含关闭时复现旧病灶）。

几何取自 s02 退想斋真实 recog（主列宽 W≈48，夹注两半 w≈30/27，右半在前）。
"""
import os

import interlinear
import proof_model


# ---- 主列 + 夹注两半（正对）----
def _lines_with_interlinear():
    return [
        {"text": "首行", "box": [266, 50, 309, 140], "score": 0.99},
        {"text": "甲乙", "box": [280, 150, 310, 364], "score": 0.95},   # 夹注右半（cx大，在前）
        {"text": "丙丁", "box": [259, 160, 286, 341], "score": 0.96},   # 夹注左半（cx小，在后）
        {"text": "末行", "box": [243, 400, 313, 490], "score": 0.98},
    ]


def test_valid_pair_merges_right_then_left():
    out = interlinear.pair_and_merge(_lines_with_interlinear())
    syn = [l for l in out if l.get("interlinear")]
    assert len(syn) == 1
    s = syn[0]
    assert s["text"] == "甲乙丙丁"                     # 右半 + 左半
    assert s["member_texts"] == ["甲乙", "丙丁"]
    assert s["score"] == 0.95                          # min(0.95, 0.96)
    assert s["box"] == [259, 150, 310, 364]            # 并集
    # 两半已被合并，不再单独出现
    texts = [l["text"] for l in out]
    assert "甲乙" not in texts and "丙丁" not in texts
    assert "首行" in texts and "末行" in texts


def test_fake_broken_halfwidth_row_not_paired():
    """碎裂半宽噪声行：两窄行上下堆叠（无 y 重叠）→ 不是夹注对，一律不动（宁漏勿错）。"""
    lines = [
        {"text": "首行", "box": [266, 50, 309, 140], "score": 0.99},
        {"text": "碎块甲", "box": [280, 100, 308, 300], "score": 0.6},
        {"text": "碎块乙", "box": [280, 320, 308, 520], "score": 0.6},   # 同 x、无 y 重叠
        {"text": "末行", "box": [243, 400, 313, 490], "score": 0.98},
    ]
    out = interlinear.pair_and_merge(lines)
    assert not any(l.get("interlinear") for l in out)
    assert {l["text"] for l in out} == {"首行", "碎块甲", "碎块乙", "末行"}


def test_non_interlinear_page_is_noop():
    """全主列宽页（无夹注）→ 严格 no-op（零回归保证）。"""
    lines = [
        {"text": "列一", "box": [266, 50, 309, 600], "score": 0.99},
        {"text": "列二", "box": [210, 50, 258, 600], "score": 0.98},
        {"text": "列三", "box": [156, 50, 205, 600], "score": 0.97},
    ]
    out = interlinear.pair_and_merge(lines)
    assert out == lines
    assert not any(l.get("interlinear") for l in out)


def test_fewer_than_three_lines_noop():
    lines = [{"text": "甲乙", "box": [280, 150, 310, 364], "score": 0.9}]
    assert interlinear.pair_and_merge(lines) == lines


def test_disabled_env_is_noop():
    old = os.environ.get("SHUPAI_INTERLINEAR")
    os.environ["SHUPAI_INTERLINEAR"] = "0"
    try:
        out = interlinear.pair_and_merge(_lines_with_interlinear())
        assert not any(l.get("interlinear") for l in out)
    finally:
        if old is None:
            os.environ.pop("SHUPAI_INTERLINEAR", None)
        else:
            os.environ["SHUPAI_INTERLINEAR"] = old


# ---- 全链：build_proof 读序 ----
def _proof_text(recog):
    proof = proof_model.build_proof(recog)
    return "".join(proof_model.assemble_paragraphs(proof))


_RECOG = {
    "p1": {
        "image": "p1.png", "width": 400, "height": 600,
        "lines": [dict(l) for l in _lines_with_interlinear()],
    }
}


def test_full_chain_interlinear_contiguous_and_ordered():
    os.environ.pop("SHUPAI_INTERLINEAR", None)   # 默认开
    text = _proof_text(_RECOG)
    assert "甲乙丙丁" in text          # 夹注右→左连续，未被主文交错
    assert "丙丁甲乙" not in text
    assert text == "首行甲乙丙丁末行"


def test_full_chain_disabled_reproduces_scramble():
    """关闭夹注合并即复现旧病灶：aggregate_columns 纯 y-sort 把两半交错颠倒。"""
    os.environ["SHUPAI_INTERLINEAR"] = "0"
    try:
        text = _proof_text(_RECOG)
        assert text == "首行丙丁甲乙末行"   # 两半被 y-sort 拆错序
        assert "甲乙丙丁" not in text
    finally:
        os.environ.pop("SHUPAI_INTERLINEAR", None)
