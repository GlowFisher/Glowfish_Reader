# -*- coding: utf-8 -*-
"""t2s_fixes 修正层单测：OpenCC t2s 漏网字（日式简化字/舖）在简体输出侧被修正。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t2s_fixes
import proof_model as M


def test_apply_fixes_shinjitai_chars():
    assert t2s_fixes.apply("戦争と平和") == "战争と平和"      # 只修字表内的字，假名不动
    assert t2s_fixes.apply("当舖の店発図広伝") == "当铺の店发图广传"
    assert t2s_fixes.apply("") == ""
    assert t2s_fixes.apply(None) is None


def test_apply_leaves_normal_simplified_untouched():
    s = "武氏新建祠堂记，奉诏迁太原。"
    assert t2s_fixes.apply(s) == s


def _mini_proof(text):
    return {"script": "t", "pages": [{"page_id": "p1", "width": 10, "height": 10,
            "lines": [{"id": "p1__0", "text": text}], "order": ["p1__0"]}]}


def test_convert_proof_to_s_applies_fixes():
    p = _mini_proof("戦後経済図")                    # 日式简化字，OpenCC t2s 原样漏过
    M.convert_proof(p, "s")
    assert p["pages"][0]["lines"][0]["text"] == "战后经济图"


def test_convert_proof_to_t_does_not_apply_fixes():
    p = _mini_proof("战后经济")
    p["script"] = "s"
    M.convert_proof(p, "t")
    t = p["pages"][0]["lines"][0]["text"]
    assert "戦" not in t                             # 繁向走 OpenCC s2t，不引入日式字形
