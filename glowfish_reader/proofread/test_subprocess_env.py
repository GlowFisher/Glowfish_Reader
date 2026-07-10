# -*- coding: utf-8 -*-
import subprocess_env


def test_clean_subprocess_env_clears_proxy_vars_and_sets_utf8(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.example")
    monkeypatch.setenv("http_proxy", "http://proxy.example")
    monkeypatch.setenv("https_proxy", "http://proxy.example")
    monkeypatch.setenv("all_proxy", "http://proxy.example")
    monkeypatch.setenv("KEEP_ME", "1")

    env = subprocess_env.clean_subprocess_env()

    assert env["HTTP_PROXY"] == ""
    assert env["HTTPS_PROXY"] == ""
    assert env["ALL_PROXY"] == ""
    assert env["http_proxy"] == ""
    assert env["https_proxy"] == ""
    assert env["all_proxy"] == ""
    assert env["NO_PROXY"] == "*"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["KEEP_ME"] == "1"
