# -*- coding: utf-8 -*-
"""能力自检的护栏：它必须真能发现缺件，否则这道闸门是摆设。"""
import io

import capabilities


def test_all_assets_present_in_source_tree():
    report = capabilities.capabilities()
    missing = {k: v["missing"] for k, v in report.items() if not v["ok"]}
    assert not missing, f"源码树里就缺资产：{missing}"
    assert capabilities.missing_labels() == []


def test_selftest_returns_zero_when_complete():
    buf = io.StringIO()
    assert capabilities.selftest(stream=buf) == 0
    assert "自检通过" in buf.getvalue()


def test_missing_asset_is_detected(tmp_path, monkeypatch):
    """把 lexicon 指到空目录，自检必须 FAIL 且退出码非零。"""
    monkeypatch.setattr(capabilities, "_LEXICON", tmp_path / "nope")
    monkeypatch.setitem(
        capabilities._REQUIRED,
        "lexicon",
        ("词表", [tmp_path / "nope" / "domain_fixes.txt"]),
    )

    report = capabilities.capabilities()
    assert report["lexicon"]["ok"] is False
    assert report["lexicon"]["missing"]
    assert "词表" in capabilities.missing_labels()

    buf = io.StringIO()
    assert capabilities.selftest(stream=buf) == 1
    assert "未通过" in buf.getvalue()
