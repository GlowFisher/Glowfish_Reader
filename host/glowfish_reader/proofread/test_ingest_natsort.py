# -*- coding: utf-8 -*-
"""自然排序键单测：导入整目录时数字文件名按数值排序（1<2<10<11），而非字典序。"""
import ingest


def test_natkey_orders_numeric_by_value():
    names = ["10.jpg", "2.jpg", "1.jpg", "11.jpg", "a.png"]
    ordered = sorted(names, key=ingest._natkey)
    assert ordered == ["1.jpg", "2.jpg", "10.jpg", "11.jpg", "a.png"]


def test_natkey_mixed_prefix():
    names = ["img12.png", "img2.png", "img1.png"]
    ordered = sorted(names, key=ingest._natkey)
    assert ordered == ["img1.png", "img2.png", "img12.png"]
