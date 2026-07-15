# -*- coding: utf-8 -*-
"""迭代3b 单测：confusion 组 / 词锚 / 概率比选择 一正一反；纠错集成（有模型才跑）。"""
import math

import numpy as np
import pytest

import ocr_correct as oc


@pytest.fixture(autouse=True)
def _isolate_globals():
    """注入型单测会改 oc 模块全局，跑完还原，防污染 build_proof 路径的真实纠错。"""
    saved = (oc._SESS, oc._VOCAB, oc._META, oc._CONF, oc._BIGRAMS)
    yield
    oc._SESS, oc._VOCAB, oc._META, oc._CONF, oc._BIGRAMS = saved


def test_confusion_groups_bidirectional():
    conf = oc.load_confusion()
    assert "盗" in conf["盐"] and "盐" in conf["盗"]      # 盐↔盗 双向
    assert "辨" in conf["办"]                              # 办↔辨
    assert "已" in conf["己"] and "巳" in conf["己"]       # 已己巳
    assert "盐" not in conf.get("办", set())               # 不跨组


def test_word_anchor_bigram():
    oc._BIGRAMS = {"办理", "盐号"}
    assert oc._word_anchor("接x理", 1, "办") is True       # 办+理=办理 ✓
    assert oc._word_anchor("x号事", 0, "盐") is True        # 盐+号=盐号 ✓
    assert oc._word_anchor("接x理", 1, "盗") is False       # 盗理/接盗 皆非词


def test_best_alt_picks_max_nonorig_and_ratio():
    oc._VOCAB = {"办": 0, "辨": 1, "难": 2}
    row = np.array([1.0, 3.0, 0.5])                        # 办=1 辨=3 难=0.5
    best, ratio = oc._best_alt(row, "办", {"办", "辨", "难"})
    assert best == "辨"                                     # 概率比最高的非原字
    assert abs(ratio - math.exp(3.0 - 1.0)) < 1e-6         # exp(Δlogit)


def test_best_alt_no_alternative():
    oc._VOCAB = {"办": 0}
    assert oc._best_alt(np.array([1.0]), "办", {"办"})[0] is None


@pytest.mark.skipif(not oc.available(), reason="MLM 模型未构建（models/mlm/）")
def test_correct_page_fixes_classical_error():
    """古典语境已知错字应被 Tier A 修正（己→已），且不动无误行。"""
    oc._SESS = None                                        # 强制重载真实资产
    lines = [
        {"id": "p__0", "text": "数月矣己数月矣", "box": [0, 0, 10, 100], "score": 0.6},
        {"id": "p__1", "text": "学而时习之", "box": [0, 0, 10, 100], "score": 0.99},
    ]
    oc.correct_page(lines)
    # 第2行无 confusion 触发字、且高分 → 不应有 corrections
    assert not lines[1].get("corrections")
