# -*- coding: utf-8 -*-
"""update_api 单测：检查决策、进度状态机、下载完成/坏哈希分支、apply 未就绪守卫、关窗钩子。

HTTP 路由 + 下载线程 + Popen 拉起安装器走 clean-VM 端到端，不在单测内。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import updater
import update_api


@pytest.fixture(autouse=True)
def _reset_state():
    update_api._reset()
    yield
    update_api._reset()


def test_check_status_no_update(monkeypatch):
    monkeypatch.setattr(updater, "fetch_manifest", lambda *a, **k: None)
    r = update_api.check_status()
    assert r["has_update"] is False
    assert r["current"] == updater.current_version()


def test_check_status_has_update(monkeypatch):
    monkeypatch.setattr(updater, "fetch_manifest", lambda *a, **k: {
        "latest": "9.9.9", "url": "https://x/s.exe", "sha256": "ab", "notes": "n", "size": 9})
    r = update_api.check_status()
    assert r["has_update"] is True and r["latest"] == "9.9.9"
    assert r["current"] == updater.current_version()


def test_read_progress_default_idle():
    assert update_api.read_progress()["phase"] == "idle"


def test_do_download_ready_on_good_sha(monkeypatch, tmp_path):
    info = {"latest": "9.9.9", "url": "https://x/s.exe", "sha256": "good", "size": 5}

    def fake_dl(url, dest, progress_cb=None, **k):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"data")
        if progress_cb:
            progress_cb(4, 4)
        return Path(dest)

    monkeypatch.setattr(updater, "download", fake_dl)
    monkeypatch.setattr(updater, "verify_sha256", lambda *a, **k: True)
    monkeypatch.setattr(update_api, "_download_dir", lambda: tmp_path)
    update_api._do_download(info)
    st = update_api.read_progress()
    assert st["phase"] == "ready" and st["file"]


def test_do_download_errors_on_bad_sha(monkeypatch, tmp_path):
    info = {"latest": "9.9.9", "url": "https://x/s.exe", "sha256": "bad", "size": 5}

    def fake_dl(url, dest, progress_cb=None, **k):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"d")
        return Path(dest)

    monkeypatch.setattr(updater, "download", fake_dl)
    monkeypatch.setattr(updater, "verify_sha256", lambda *a, **k: False)
    monkeypatch.setattr(update_api, "_download_dir", lambda: tmp_path)
    update_api._do_download(info)
    st = update_api.read_progress()
    assert st["phase"] == "error" and st["error"] == "sha256_mismatch"


def test_apply_guards_when_not_ready(monkeypatch):
    called = []
    monkeypatch.setattr(updater, "launch_installer", lambda p: called.append(p))
    r = update_api.api_apply()
    assert r["ok"] is False and r["reason"] == "not_ready"
    assert called == []        # 未就绪时绝不拉起安装器


def test_shutdown_hook_invoked():
    flag = []
    update_api.register_shutdown(lambda: flag.append(1))
    update_api._request_shutdown()
    assert flag == [1]
