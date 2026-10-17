# -*- coding: utf-8 -*-
"""A1 单测：域词确定性修复层（纯数据表 + 纯函数，不载模型）。"""
import os

import domain_fixes as D


def _reload_rules():
    D._RULES = None
    return D.load_rules()


def test_table_loads_and_is_longest_first():
    rules = _reload_rules()
    assert rules, "domain_fixes.txt 应有条目"
    lens = [len(w) for w, _ in rules]
    assert lens == sorted(lens, reverse=True), "长词锚必须排在前，否则短锚会抢先改坏长锚"


def test_no_single_char_rule_can_load():
    """纪律闸：单字裸换永不入表（形近对不携带方向）。"""
    assert all(len(w) >= 2 for w, _ in _reload_rules())


def test_salt_domain_fixes_applied():
    text, corr = D.apply_text("黔省组织之利民盛号今已全部筹组就绪")
    assert "利民盐号" in text
    assert corr and corr[0]["rule"] == "domain_word"


def test_ban_to_bian_fixed():
    text, _ = D.apply_text("大业过去辨理盘八一隅")
    assert "办理盘八" in text


def test_untouched_text_unchanged():
    src = "今日为阳历二月二号係开保存古物委员会期"
    text, corr = D.apply_text(src)
    assert text == src and corr == []


def test_audited_trap_not_in_table():
    """「国难」是合法词（干净语料 6 次命中），审计已 REJECT，绝不能出现在表里。"""
    assert all(w != "国难" for w, _ in _reload_rules())
    src = "值此国难当头之际"
    text, _ = D.apply_text(src)
    assert text == src, "「国难」不得被改成「困难」"


def test_zhixu_needs_long_anchor():
    """「之虚」两字锚在干净语料命中 54 次，只准三字锚「缓之虚」。"""
    assert all(w != "之虚" for w, _ in _reload_rules())
    src = "盈之虚之天道也"
    text, _ = D.apply_text(src)
    assert text == src


def test_correct_page_records_corrections():
    lines = [{"id": "p__0", "text": "利民盛号承辨仁岸"}]
    D.correct_page(lines)
    assert lines[0]["text"] == "利民盐号承办仁岸"
    assert len(lines[0]["corrections"]) == 2


def test_correct_page_skips_deleted():
    lines = [{"id": "p__0", "text": "利民盛号", "deleted": True}]
    D.correct_page(lines)
    assert lines[0]["text"] == "利民盛号"


def test_env_switch_off(monkeypatch):
    monkeypatch.setenv("SHUPAI_DOMAIN_FIXES", "0")
    src = "利民盛号"
    text, corr = D.apply_text(src)
    assert text == src and corr == []
