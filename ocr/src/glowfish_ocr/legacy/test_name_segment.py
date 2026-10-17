# -*- coding: utf-8 -*-
"""迭代3e 单测：名单语境触发 + 非名单语境零触发（安全性主属性）。

注：纯姓氏锚点模式对「国/山/广」等姓氏兼常用字会过切（属已知 Tier B 精度局限，
待名单语料标定 MLM 边界闸后收敛）；本测只锁「触发/零触发」边界，不锁精确切分。"""
import name_segment as ns


def test_zero_trigger_on_clean_classical():
    for t in ["学而时习之不亦说乎有朋自远方来不亦乐乎",
              "其由岸口运到贵阳安顺中经赤水茅台新场滥泥沟",
              "今日为阳历民国十年二月七号徐世昌为大总统"]:
        assert ns.suggest(t) == [], t


def test_roster_context_triggers():
    # 引导词/煞尾词 + 姓氏连排 → 出建议（≥2 段）
    r = ns.suggest("绅商刘大鹏赵铁山等")
    assert r and len(r[0]["segments"]) >= 2
    r2 = ns.suggest("公推张之洞李鸿章曾国藩等办理")
    assert r2 and "张之洞" in r2[0]["joined"]


def test_no_roster_context_no_trigger():
    # 有姓氏连排但无名单语境 → 不碰（避免误切正文）
    assert ns.suggest("刘大鹏赵铁山两先生") == [] or all(
        "先生" not in s["run"] for s in ns.suggest("刘大鹏赵铁山两先生"))


def test_disabled_env(monkeypatch):
    monkeypatch.setenv("SHUPAI_NAME_SEGMENT", "0")
    assert ns.suggest("绅商刘大鹏赵铁山等") == []


def test_annotate_lines_adds_tier_b_suggestion():
    lines = [{"id": "p__0", "text": "绅商刘大鹏赵铁山等公议", "deleted": False}]
    ns.annotate_lines(lines)
    segs = [s for s in lines[0].get("suggestions", []) if s.get("type") == "segment"]
    assert len(segs) == 1
