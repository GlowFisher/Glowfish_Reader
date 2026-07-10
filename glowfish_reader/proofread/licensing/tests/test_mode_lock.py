# -*- coding: utf-8 -*-
"""打包态运行模式锁定：授权门不可经 SHUPAI_MODE 环境变量绕过。"""
import appconfig


def test_frozen_locks_single_ignoring_env(monkeypatch):
    monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
    monkeypatch.setattr(appconfig, "_read_bundle_sku", lambda: "single")
    monkeypatch.setenv("SHUPAI_MODE", "multi")          # 试图绕过授权门
    assert appconfig.get_mode() == "single"
    assert appconfig.is_single() is True


def test_frozen_multi_sku(monkeypatch):
    monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
    monkeypatch.setattr(appconfig, "_read_bundle_sku", lambda: "multi")
    monkeypatch.setenv("SHUPAI_MODE", "single")
    assert appconfig.get_mode() == "multi"


def test_frozen_missing_marker_defaults_single(monkeypatch):
    monkeypatch.setattr(appconfig, "is_frozen", lambda: True)
    monkeypatch.setattr(appconfig, "_read_bundle_sku", lambda: "")
    assert appconfig.get_mode() == "single"


def test_dev_mode_defaults_single_and_ignores_env(monkeypatch):
    monkeypatch.setattr(appconfig, "is_frozen", lambda: False)
    monkeypatch.setenv("SHUPAI_MODE", "multi")
    assert appconfig.get_mode() == "single"
    assert appconfig.is_single() is True
