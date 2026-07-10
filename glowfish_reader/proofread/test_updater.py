# -*- coding: utf-8 -*-
"""updater 鏍稿績鍗曟祴锛氱増鏈В鏋?姣旇緝銆佹洿鏂板喅绛栥€乻ha256 鏍￠獙銆佹竻鍗曟媺鍙栥€佷笅杞借繘搴︺€?

Windows 闆嗘垚閮ㄥ垎锛坙aunch_installer 鎷夎捣瀹夎鍣ㄣ€佸叧绐楅噸鍚級涓嶅湪鍗曟祴鍐咃紝璧?clean-VM 楠屾敹銆?
"""
import sys
import json
import hashlib
import threading
import functools
import http.server
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import updater
import _version


# ---- 鐗堟湰瑙ｆ瀽 / 姣旇緝 ----
def test_parse_version_basic():
    assert updater.parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_tolerates_v_prefix_and_spaces():
    assert updater.parse_version(" v1.0.0 ") == (1, 0, 0)


def test_is_newer_true():
    assert updater.is_newer("1.1.0", "1.0.0") is True


def test_is_newer_false_when_equal():
    assert updater.is_newer("1.0.0", "1.0.0") is False


def test_is_newer_false_when_older():
    assert updater.is_newer("1.0.0", "1.1.0") is False


def test_is_newer_numeric_not_lexical():
    # 1.10.0 姣?1.9.0 鏂帮紙10 > 9 鏁板瓧姣旇緝锛岃€岄潪瀛楀吀搴?"10" < "9"锛?
    assert updater.is_newer("1.10.0", "1.9.0") is True


def test_current_version_reads_single_source():
    assert updater.current_version() == _version.__version__


# ---- 娓呭崟鍦板潃瑙ｆ瀽 manifest_url ----
def test_manifest_url_default(monkeypatch):
    monkeypatch.delenv("SHUPAI_UPDATE_URL", raising=False)
    monkeypatch.delenv("SHUPAI_LICENSE_SERVER", raising=False)
    assert updater.manifest_url() == "https://license.glowfishreader.com/update.json"


def test_manifest_url_explicit_override(monkeypatch):
    monkeypatch.setenv("SHUPAI_UPDATE_URL", "http://127.0.0.1:9/u.json")
    assert updater.manifest_url() == "http://127.0.0.1:9/u.json"


def test_manifest_url_derived_from_license_server(monkeypatch):
    monkeypatch.delenv("SHUPAI_UPDATE_URL", raising=False)
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", "https://example.com/")
    assert updater.manifest_url() == "https://example.com/update.json"


# ---- 鏇存柊鍐崇瓥 evaluate ----
def test_evaluate_no_manifest_means_no_update():
    assert updater.evaluate("1.0.0", None)["has_update"] is False


def test_evaluate_same_version_means_no_update():
    assert updater.evaluate("1.0.0", {"latest": "1.0.0"})["has_update"] is False


def test_evaluate_newer_optional():
    r = updater.evaluate("1.0.0", {
        "latest": "1.1.0", "min_supported": "1.0.0",
        "url": "https://x/setup.exe", "sha256": "abc", "notes": "鏇存柊鍐呭", "size": 5})
    assert r["has_update"] is True
    assert r["mandatory"] is False
    assert r["latest"] == "1.1.0"
    assert r["url"] == "https://x/setup.exe"
    assert r["notes"] == "鏇存柊鍐呭"


def test_evaluate_mandatory_via_flag():
    r = updater.evaluate("1.0.0", {"latest": "1.1.0", "mandatory": True})
    assert r["has_update"] is True and r["mandatory"] is True


def test_evaluate_mandatory_when_below_min_supported():
    # 褰撳墠鐗堟湰浣庝簬 min_supported锛堝杞崲鏈嶅姟鍣ㄥ瘑閽ュ悗鏃х増蹇呴』鍗囷級鈫?寮哄埗
    r = updater.evaluate("1.0.0", {"latest": "1.2.0", "min_supported": "1.1.0"})
    assert r["has_update"] is True and r["mandatory"] is True


# ---- 娓呭崟 v2锛歝ode 灏忓寘浼樺厛 / 鏃у瓧娈靛吋瀹?----
def test_evaluate_prefers_code_package_when_present():
    r = updater.evaluate("1.0.0", {
        "latest": "1.1.0", "url": "https://x/full.exe", "sha256": "full", "size": 999,
        "code": {"url": "https://x/code.exe", "sha256": "code", "size": 5}})
    assert r["url"] == "https://x/code.exe"
    assert r["sha256"] == "code" and r["size"] == 5


def test_evaluate_falls_back_to_legacy_fields_without_code():
    r = updater.evaluate("1.0.0", {"latest": "1.1.0",
                                   "url": "https://x/full.exe", "sha256": "full", "size": 9})
    assert r["url"] == "https://x/full.exe" and r["sha256"] == "full"


def test_evaluate_ignores_incomplete_code_object():
    # code 缂?sha256 瑙嗕负娈嬬己 鈫?鍥炶惤鏃у瓧娈碉紝缁濅笉涓嬫棤娉曟牎楠岀殑鍖?
    r = updater.evaluate("1.0.0", {"latest": "1.1.0", "url": "https://x/full.exe",
                                   "sha256": "full", "size": 9, "code": {"url": "https://x/c.exe"}})
    assert r["url"] == "https://x/full.exe" and r["sha256"] == "full"


# ---- sha256 鏍￠獙 ----
def test_verify_sha256_match(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert updater.verify_sha256(p, hashlib.sha256(b"hello").hexdigest()) is True


def test_verify_sha256_case_insensitive(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert updater.verify_sha256(p, hashlib.sha256(b"hello").hexdigest().upper()) is True


def test_verify_sha256_mismatch(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert updater.verify_sha256(p, "deadbeef") is False


# ---- 娓呭崟鎷夊彇 / 涓嬭浇锛堟湰鍦?http.server 闆嗘垚锛?---
@pytest.fixture
def http_dir(tmp_path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        yield tmp_path, f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


def test_fetch_manifest_ok(http_dir):
    d, base = http_dir
    (d / "update.json").write_text(json.dumps({"latest": "1.1.0"}), encoding="utf-8")
    m = updater.fetch_manifest(base + "/update.json")
    assert m["latest"] == "1.1.0"


def test_fetch_manifest_network_failure_is_soft_none():
    # 涓嶅彲杈剧鍙?鈫?杞け璐ヨ繑鍥?None锛堜笉鎶涳紝浠?licensing/client 鐨勮蒋杩斿洖锛?
    assert updater.fetch_manifest("http://127.0.0.1:1/update.json", timeout=1) is None


def test_download_writes_file_and_reports_progress(http_dir, tmp_path):
    d, base = http_dir
    payload = b"x" * 100000
    (d / "app.bin").write_bytes(payload)
    seen = []
    dest = tmp_path / "out.bin"
    updater.download(base + "/app.bin", dest,
                     progress_cb=lambda done, total: seen.append((done, total)))
    assert dest.read_bytes() == payload
    assert updater.verify_sha256(dest, hashlib.sha256(payload).hexdigest()) is True
    assert seen and seen[-1][0] == len(payload)
