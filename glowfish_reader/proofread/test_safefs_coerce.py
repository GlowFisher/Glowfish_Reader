# -*- coding: utf-8 -*-
"""coerce_batch 目录名安全：智能拆分按文件名建 batch，须规避 Windows 保留名/结尾点/超长。"""
import safefs


def test_reserved_name_prefixed():
    assert safefs.coerce_batch("con") == "_con"        # CON 作目录名在 Windows 非法 → 加前缀
    assert safefs.coerce_batch("LPT1") == "_LPT1"
    assert safefs.coerce_batch("aux") == "_aux"


def test_trailing_dot_space_stripped():
    assert safefs.coerce_batch("名稿....") == "名稿"     # 结尾点被剥
    assert safefs.coerce_batch("稿 ") == "稿"


def test_empty_and_dots_fallback():
    assert safefs.coerce_batch("....") == "import"     # 全点剥光 → 兜底
    assert safefs.coerce_batch("") == "import"
    assert safefs.coerce_batch("..") == "import"


def test_length_capped():
    assert len(safefs.coerce_batch("甲" * 300)) == 120


def test_normal_name_unchanged():
    assert safefs.coerce_batch("Needham0010") == "Needham0010"
    assert safefs.coerce_batch("1") == "1"
