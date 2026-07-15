import base64
import importlib
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
from glowfish_account_server import sign


def _client(monkeypatch, tmp_path):
    srv_sk = SigningKey.generate()
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", "http://account.test")

    proofread_dir = str(Path(__file__).resolve().parent)
    if proofread_dir in sys.path:
        sys.path.remove(proofread_dir)
    sys.path.insert(0, proofread_dir)
    sys.modules.pop("server", None)
    import appconfig
    import auth_api
    import license_api
    import userctx
    import server
    from licensing import keys

    monkeypatch.setattr(keys, "SERVER_PUB", base64.b64encode(bytes(srv_sk.verify_key)).decode())
    importlib.reload(appconfig)
    importlib.reload(license_api)
    importlib.reload(auth_api)
    importlib.reload(userctx)
    importlib.reload(server)
    return TestClient(server.app), srv_sk


def _account_response(sk, session_id="S1", status="trial", tier="trial", expires_at=None,
                      checked_at=None):
    exp = expires_at or int(time.time()) + 7 * 86400
    account = {
        "user_id": 7,
        "username": "13800138000",
        "display": "13800138000",
        "phone": "13800138000",
        "status": status,
        "tier": tier,
        "expires_at": exp,
        "trial_expires_at": exp if status == "trial" else 0,
        "subscription_expires_at": exp if status == "member" else 0,
        "allowed": status in ("trial", "member"),
    }
    cred = sign.make_signed({
        "typ": "account",
        "session_id": session_id,
        "user_id": 7,
        "username": "13800138000",
        "status": status,
        "tier": tier,
        "expires_at": exp,
        "checked_at": checked_at or int(time.time()),
    }, base64.b64encode(bytes(sk)).decode())
    return {"ok": True, "session_id": session_id, "cred": cred, "account": account}


def test_phone_register_saves_account_credential_and_me_returns_entitlement(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)

    import licensing.client as remote
    monkeypatch.setattr(remote, "account_register_phone",
                        lambda phone, code, password, fp, app_version: _account_response(sk))

    r = client.post("/api/register/phone", json={
        "phone": "13800138000", "code": "123456", "password": "secret1"
    })

    assert r.status_code == 200
    assert r.json()["ok"] is True
    me = client.get("/api/me").json()
    assert me["username"] == "13800138000"
    assert me["entitlement"]["mode"] == "trial"


def test_password_login_rejects_bad_account_signature(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)

    import licensing.client as remote
    monkeypatch.setattr(remote, "account_login_password", lambda login, password, fp, app_version: {
        "ok": True,
        "session_id": "S1",
        "cred": "bad",
        "account": {"username": "13800138000", "status": "trial"},
    })

    r = client.post("/api/login/password", json={"login": "13800138000", "password": "secret1"})

    # detail 现由 account_errors 统一映射中文（bad_account_cred），不再是英文原文
    import account_errors
    assert r.status_code == 400
    assert r.json()["detail"] == account_errors.msg("bad_account_cred")


def test_account_check_refreshes_member_entitlement(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)

    import licensing.client as remote
    monkeypatch.setattr(remote, "account_login_password",
                        lambda login, password, fp, app_version: _account_response(sk, session_id="S2"))
    monkeypatch.setattr(remote, "account_check",
                        lambda session_id, fp, app_version: _account_response(
                            sk, session_id=session_id, status="member", tier="member"))
    assert client.post("/api/login/password", json={"login": "13800138000", "password": "secret1"}).json()["ok"]

    # /api/account/check 路由已删（前端从不调用；启动静默核对走 /api/me → account_gate），
    # 权益刷新逻辑直接测 license_api.account_check()。
    import license_api
    checked = license_api.account_check()

    assert checked["ok"] is True
    assert checked["account"]["status"] == "member"
    assert client.get("/api/me").json()["entitlement"]["mode"] == "member"


# 原 test_require_license_uses_account_status 已移除：其断言的 license_api.require_license()
# 属激活码授权闸，已随「退役激活码」(6671d54d) 一并删除，生产代码无任何引用。
# 账号状态的等价校验由上方 test_account_check_refreshes_entitlement 覆盖。


# ---- 免登录 + 断网宽限（/api/me 启动静默核对）----

DAY = 86400


def _login(client, sk, monkeypatch, **resp_kw):
    import licensing.client as remote
    monkeypatch.setattr(remote, "account_login_password",
                        lambda login, password, fp, app_version: _account_response(sk, **resp_kw))
    r = client.post("/api/login/password", json={"login": "13800138000", "password": "secret1"})
    assert r.json().get("ok"), r.text
    return remote


def _force_probe():
    """把节流计时清零，让下一次 /api/me 必然联网核对。"""
    import license_api
    license_api._last_probe_ts = 0


def test_me_probes_server_and_blocks_when_session_rejected(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    remote = _login(client, sk, monkeypatch)

    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "session_expired"})
    _force_probe()

    me = client.get("/api/me").json()
    assert me.get("single") is True      # 被服务器明确拒绝 → 视为未登录，弹登录闸


def test_me_allows_offline_within_grace(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    now = int(time.time())
    remote = _login(client, sk, monkeypatch, checked_at=now - 13 * DAY)

    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})
    _force_probe()

    me = client.get("/api/me").json()
    assert me.get("username") == "13800138000"      # 断网 13 天：宽限期内放行


def test_me_blocks_offline_beyond_grace(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    now = int(time.time())
    remote = _login(client, sk, monkeypatch, checked_at=now - 15 * DAY)

    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})
    _force_probe()

    me = client.get("/api/me").json()
    assert me.get("single") is True      # 断网超 14 天：必须联网重新核对/登录


def test_me_blocks_signed_expiry_even_offline(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    now = int(time.time())
    # 会员昨天到期（到期时间在签名凭据内，改本机 json 无效）；断网仍在 14 天宽限内
    remote = _login(client, sk, monkeypatch, expires_at=now - DAY, checked_at=now - 3600)

    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})
    _force_probe()

    me = client.get("/api/me").json()
    assert me.get("single") is True      # 使用期限已过：断网也不放行


def test_me_probe_is_throttled(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    remote = _login(client, sk, monkeypatch)

    calls = []
    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: (calls.append(1), _account_response(sk))[1])

    # 刚登录过（等于刚联过网）：/api/me 不再立即联网
    assert client.get("/api/me").json()["username"] == "13800138000"
    assert calls == []

    _force_probe()
    assert client.get("/api/me").json()["username"] == "13800138000"
    assert len(calls) == 1
    # 节流窗口内第二次 /api/me 不重复联网
    assert client.get("/api/me").json()["username"] == "13800138000"
    assert len(calls) == 1


# ---- 防时钟回拨 + 登录计数口径 + 断网重试 + 到期文案 ----

EXPIRED_NOTICE = "您的使用期限已到期，可前往 http://glowfishreader.com 找管理员续期"


def _rollback_clock(monkeypatch, fake_now):
    """只在 license_api 模块内伪造 time.time（store/其它模块不受影响）。"""
    import types
    import license_api
    monkeypatch.setattr(license_api, "time", types.SimpleNamespace(time=lambda: float(fake_now)))


def test_me_blocks_grace_bypass_via_clock_rollback(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    now = int(time.time())
    # 上次核对是 15 天前（宽限已破），用户把系统时钟回拨 14 天让它看起来只过了 1 天
    remote = _login(client, sk, monkeypatch, checked_at=now - 15 * DAY)
    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})
    _rollback_clock(monkeypatch, now - 14 * DAY)

    me = client.get("/api/me").json()
    assert me.get("single") is True      # 单调钟应识破回拨：宽限已破，仍须联网


def test_me_blocks_expiry_bypass_via_clock_rollback(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    now = int(time.time())
    # 会员昨天到期，用户把时钟回拨两天假装没到期
    remote = _login(client, sk, monkeypatch, expires_at=now - DAY, checked_at=now - 3600)
    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})
    _rollback_clock(monkeypatch, now - 2 * DAY)

    me = client.get("/api/me").json()
    assert me.get("single") is True      # 单调钟记得见过 now：到期照拦


def test_probe_counts_login_once_per_process(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    remote = _login(client, sk, monkeypatch)

    flags = []
    monkeypatch.setattr(remote, "account_check",
                        lambda session_id, fp, app_version, count_login=False:
                        (flags.append(count_login), _account_response(sk))[1])

    _force_probe()
    client.get("/api/me")
    assert flags == [False]      # 本进程刚手动登录（服务端已计数），探测不再计

    # 模拟带凭据冷启动的新进程：未计过数 → 首个探测计一次，其后心跳不计
    import license_api
    license_api._last_probe_ts = 0
    license_api._login_counted = False
    client.get("/api/me")
    _force_probe()
    client.get("/api/me")
    assert flags == [False, True, False]


def test_probe_network_failure_retries_within_a_minute(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    remote = _login(client, sk, monkeypatch)
    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "network"})

    import license_api
    _force_probe()
    client.get("/api/me")      # 探测失败

    # 失败不应烧掉整个 1 小时节流窗：下次重试须在 60 秒内到点
    cooldown_left = license_api._PROBE_INTERVAL - (time.time() - license_api._last_probe_ts)
    assert cooldown_left <= 60


def test_me_carries_expired_notice_after_server_rejects(monkeypatch, tmp_path):
    client, sk = _client(monkeypatch, tmp_path)
    remote = _login(client, sk, monkeypatch)
    monkeypatch.setattr(remote, "account_check",
                        lambda *a, **k: {"ok": False, "reason": "expired"})
    _force_probe()

    me = client.get("/api/me").json()
    assert me.get("single") is True
    assert me.get("notice") == EXPIRED_NOTICE      # 弹出的登录窗要能显示续期指引


def test_login_with_expired_account_shows_renewal_message(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    import licensing.client as remote
    monkeypatch.setattr(remote, "account_login_password",
                        lambda login, password, fp, app_version: {"ok": False, "reason": "expired"})

    r = client.post("/api/login/password", json={"login": "13800138000", "password": "secret1"})

    assert r.status_code == 400
    assert r.json()["detail"] == EXPIRED_NOTICE



