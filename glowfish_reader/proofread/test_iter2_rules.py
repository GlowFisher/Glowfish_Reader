# -*- coding: utf-8 -*-
"""迭代2 单测：2b 纪年非法数字字纠正 + 2c 并列短项顿号（纯函数，不载模型）。"""
import proof_model
import punctuate_local as P


# ================= 2b 纪年 =================
def test_reign_year_fixes_invalid_numeral():
    # 川 非法数字字 → 十（朝代语境）
    assert proof_model._fix_reign_year("中华民国三川年七月") == "中华民国三十年七月"
    assert proof_model._fix_reign_year("大清宣统三川年") == "大清宣统三十年"


def test_reign_year_keeps_valid_numeral_ambiguous():
    # 七 本身合法（可能是 7 或误认的 1），保守不动 → 只纠 川→十
    assert proof_model._fix_reign_year("中华民国三川七年") == "中华民国三十七年"


def test_reign_year_no_dynasty_context_noop():
    # 无朝代语境不碰（防误纠）
    assert proof_model._fix_reign_year("行三川年间") == "行三川年间"


def test_reign_year_garbled_slot_noop():
    # 槽内混入非数字字（氏國）→ 正则不匹配 → no-op（真实 s03 落款即此型）
    assert proof_model._fix_reign_year("中华民国三氏国三年七月") == "中华民国三氏国三年七月"


def test_reign_year_already_valid_noop():
    assert proof_model._fix_reign_year("中华民国三十一年七月") == "中华民国三十一年七月"


# ================= 2c 并列顿号 =================
def _mk(s):
    """把展示串拆成 (chars, puncts)：标点吸附到前一个字。"""
    chars, puncts = [], []
    for ch in s:
        if ch in "。、，；：":
            if puncts:
                puncts[-1] += ch
        else:
            chars.append(ch)
            puncts.append("")
    return chars, puncts


def _apply(s):
    chars, puncts = _mk(s)
    p2 = P._fix_enumeration_commas(chars, puncts)
    return "".join(c + p for c, p in zip(chars, p2))


def test_enum_three_names_surname_fires():
    # s02 型：广东孙文。伍廷芳。唐绍仪 → 顿号（串首「一步。」保留）
    assert _apply("一步。广东孙文。伍廷芳。唐绍仪等") == "一步。广东孙文、伍廷芳、唐绍仪等"


def test_enum_two_names_no_fire():
    # 仅两项不触发（误伤率高）
    assert _apply("张三。李四。") == "张三。李四。"


def test_enum_place_suffix_fires():
    assert _apply("赤桥村。太平村。清源村。") == "赤桥村、太平村、清源村。"


def test_enum_equal_length_no_longer_fires():
    # 纯等长形态触发已停用（防「天下。人皆。知之」误伤）
    assert _apply("天下。人皆。知之。") == "天下。人皆。知之。"


def test_enum_gate_reads_env(monkeypatch):
    # 开关在 local_punctuate 处生效（_apply 直调纯函数不经开关）
    monkeypatch.setenv("SHUPAI_ENUM_COMMA", "0")
    assert P._enum_comma_enabled() is False
    monkeypatch.setenv("SHUPAI_ENUM_COMMA", "1")
    assert P._enum_comma_enabled() is True
