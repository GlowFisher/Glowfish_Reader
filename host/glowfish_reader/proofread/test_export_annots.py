# -*- coding: utf-8 -*-
"""批注导出：v2 划批（page.annots）必须进 _annot_paras，旧三类（notes/page_annot/line.annot）不回归。"""
from export_api import _annot_paras


def _proof():
    return {
        "notes": "全局研究笔记",
        "pages": [{
            "page_id": "p1",
            "page_annot": "本页总批",
            "annots": [
                {"id": "a1", "quote": "武汉会战", "occ": 0, "note": "会战背景待考"},
                {"id": "a2", "quote": "国难", "occ": 0, "note": ""},      # 只划记未填批注
                {"id": "a3", "quote": "", "occ": 0, "note": ""},          # 空条目跳过
            ],
            "lines": [{"id": "l1", "text": "民国二十七年", "annot": "旧版段批"}],
            "order": ["l1"],
        }],
    }


def test_annot_paras_includes_v2_annots():
    paras = _annot_paras(_proof())
    joined = "\n".join(paras)
    assert "【研究笔记】全局研究笔记" in joined
    assert "〔p1〕本页总批" in joined
    assert "「武汉会战」▸ 会战背景待考" in joined      # v2 划批带批注
    assert "「国难」（划记）" in joined                # v2 只划记
    assert "旧版段批" in joined                        # 旧段批不回归
    assert joined.count("「」") == 0                   # 空条目不输出


def test_annot_paras_no_annots_key():
    """老 proof 没有 annots 键：不炸、行为不变。"""
    pf = _proof()
    del pf["pages"][0]["annots"]
    paras = _annot_paras(pf)
    assert any("旧版段批" in p for p in paras)
