# -*- coding: utf-8 -*-
"""手机号 + 短信验证码 鉴权 单元/接口自测。

隔离：SHUPAI_DATA_DIR 指向 tmp，reload appconfig/auth 使 DB 落临时目录；GF_SMS_DEV=1 回显验证码。
"""
import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture()
def mod(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GF_SMS_DEV", "1")
    monkeypatch.setenv("GF_SMS_BACKEND", "console")
    import appconfig
    import auth
    import sms
    importlib.reload(appconfig)
    importlib.reload(sms)
    importlib.reload(auth)
    return auth


P1 = "13800138000"
P2 = "13912345678"
PWD = "Abc123"


# ----------------------------- 内核层 -----------------------------

def test_register_and_login(mod):
    code = mod.issue_sms_code(P1, "register")
    assert mod.verify_sms_code(P1, "register", code)
    u = mod.create_user_by_phone(P1, PWD)
    assert u["username"] == P1
    assert mod.verify_user_by_phone(P1, PWD)
    assert mod.verify_user_by_phone(P1, "wrongpwd") is None


def test_sms_code_one_time_and_scene(mod):
    code = mod.issue_sms_code(P1, "register")
    assert mod.verify_sms_code(P1, "login", code) is False       # 场景不符
    assert mod.verify_sms_code(P1, "register", code)             # 正确场景消费
    assert mod.verify_sms_code(P1, "register", code) is False    # 已消费不可复用


def test_sms_resend_throttle(mod):
    mod.issue_sms_code(P1, "register")
    with pytest.raises(mod.AuthError):
        mod.issue_sms_code(P1, "register")                      # 60s 内重发被拦


def test_register_scene_requires_unregistered(mod):
    code = mod.issue_sms_code(P1, "register")
    mod.verify_sms_code(P1, "register", code)
    mod.create_user_by_phone(P1, PWD)
    with pytest.raises(mod.AuthError):
        mod.issue_sms_code(P1, "register")                      # 已注册不可再注册


def test_reset_flow(mod):
    code = mod.issue_sms_code(P1, "register")
    mod.verify_sms_code(P1, "register", code)
    mod.create_user_by_phone(P1, PWD)
    rcode = mod.issue_sms_code(P1, "reset")                     # 已注册可发 reset 码
    assert mod.verify_sms_code(P1, "reset", rcode)
    mod.reset_password_by_phone(P1, "NewPass9")
    assert mod.verify_user_by_phone(P1, "NewPass9")
    assert mod.verify_user_by_phone(P1, PWD) is None


def test_reset_scene_requires_registered(mod):
    with pytest.raises(mod.AuthError):
        mod.issue_sms_code(P2, "reset")                         # 未注册不可发 reset 码


def test_duplicate_phone_register(mod):
    mod.create_user_by_phone(P1, PWD)
    with pytest.raises(mod.AuthError):
        mod.create_user_by_phone(P1, PWD)


def test_invalid_phone_and_weak_password(mod):
    with pytest.raises(mod.AuthError):
        mod.create_user_by_phone("12345", PWD)                 # 非法手机号
    with pytest.raises(mod.AuthError):
        mod.create_user_by_phone(P1, "123")                    # 密码过短
    with pytest.raises(mod.AuthError):
        mod.create_user_by_phone(P1, "abc!@#定")               # 非法字符集


# ----------------------------- 接口层 -----------------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHUPAI_ACCOUNT_MODE", "member")
    monkeypatch.setenv("GF_SMS_DEV", "1")
    monkeypatch.setenv("GF_SMS_LOCAL", "1")            # 本机兜底路径：验证码走本地内核，无需起服务器
    for name in ("appconfig", "sms", "auth", "auth_api", "userctx", "server"):
        importlib.reload(importlib.import_module(name))
    import server
    return TestClient(server.app)


def _post(client, url, **data):
    return client.post(url, json=data)


def test_api_register_login_reset(client):
    # 注册：发码 → 回显 dev_code → 注册（不自动登录）
    r = _post(client, "/api/sms/send", phone=P1, scene="register")
    assert r.status_code == 200
    code = r.json()["dev_code"]
    r = _post(client, "/api/register", phone=P1, code=code, password=PWD)
    assert r.status_code == 200 and r.json()["ok"]
    assert "sid" not in r.cookies                              # 注册不下发会话

    # 登录：手机号+密码
    r = _post(client, "/api/login", phone=P1, password=PWD)
    assert r.status_code == 200
    assert r.cookies.get("sid")

    # 错误密码
    assert _post(client, "/api/login", phone=P1, password="Wrong9").status_code == 401

    # 找回：发 reset 码 → 重置 → 新密码登录
    code2 = _post(client, "/api/sms/send", phone=P1, scene="reset").json()["dev_code"]
    r = _post(client, "/api/password/reset", phone=P1, code=code2, password="NewPass9")
    assert r.status_code == 200 and r.json()["ok"]
    assert _post(client, "/api/login", phone=P1, password="NewPass9").status_code == 200


def test_api_backend_revalidates(client):
    # 绕过前端直接打接口：非法手机号 / 错误验证码 均被后端拦
    assert _post(client, "/api/sms/send", phone="123", scene="register").status_code == 400
    assert _post(client, "/api/register", phone=P1, code="000000", password=PWD).status_code == 400


def test_weak_password_does_not_consume_sms_code(client):
    """弱密码被拒后，验证码必须仍然有效——格式校验须先于验证码的一次性消费。

    回归防线：曾经 register 先校验（消费）验证码再校验密码，用户密码写太短、改好再提交
    却被告知「验证码错误或已过期」，还得重新等一条短信。"""
    code = _post(client, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]

    r = _post(client, "/api/register", phone=P1, code=code, password="123")   # 太短
    assert r.status_code == 400
    assert "密码" in r.json()["detail"]                     # 报的是密码问题，不是验证码问题

    r = _post(client, "/api/register", phone=P1, code=code, password=PWD)     # 同一个码仍可用
    assert r.status_code == 200 and r.json()["ok"]


def test_weak_password_does_not_consume_reset_code(client):
    """找回密码同理：新密码不合格不得烧掉 reset 验证码。"""
    code = _post(client, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]
    assert _post(client, "/api/register", phone=P1, code=code, password=PWD).status_code == 200

    code2 = _post(client, "/api/sms/send", phone=P1, scene="reset").json()["dev_code"]
    assert _post(client, "/api/password/reset", phone=P1, code=code2, password="1").status_code == 400
    r = _post(client, "/api/password/reset", phone=P1, code=code2, password="NewPass9")
    assert r.status_code == 200 and r.json()["ok"]
    assert _post(client, "/api/login", phone=P1, password="NewPass9").status_code == 200


# --------------------- 接口层（云账号路径：账号与验证码都在服务器） ---------------------
# ⚠此前这里测的是「远程发码 + 远程 /account/sms/verify + 本机建号」的中间形态，
#   而线上 account-server 从未部署 /account/sms/verify（2026-07-08 实测 404），
#   该设计跑不通。真实云路径是把 code 一并交给 /account/register/phone 内部校验。

@pytest.fixture()
def remote_client(monkeypatch, tmp_path):
    """默认云路径：/api/sms/send·register·login·reset 全部委托账号服务器（内存伪服务器 mock）。
    验证 auth_api 的编排（格式前置校验 + 路由到云）与 reason→中文 映射。
    license_api 与真服务器的签名/cred 契约由 test_account_api.py 覆盖，此处 mock 掉。"""
    monkeypatch.setenv("SHUPAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SHUPAI_ACCOUNT_MODE", "member")
    monkeypatch.setenv("GF_SMS_DEV", "1")
    monkeypatch.delenv("GF_SMS_LOCAL", raising=False)         # 关闭本机兜底 → 走云
    for name in ("appconfig", "sms", "auth", "auth_api", "userctx", "server"):
        importlib.reload(importlib.import_module(name))
    import auth_api
    import server
    from fastapi import HTTPException

    codes, accounts = {}, {}                                  # 伪服务器：phone->code / phone->password

    def fake_send(phone):
        codes[phone] = "654321"
        return {"ok": True, "ttl": 300, "cooldown": 60, "dev_code": codes[phone]}

    def _consume(phone, code):
        """服务端内部校验（core.sms_verify 语义）：单次消费。"""
        if codes.get(phone) and code == codes[phone]:
            del codes[phone]
            return None
        return "bad_code"

    def _raise(reason):
        import account_errors
        raise HTTPException(account_errors.status(reason), account_errors.msg(reason))

    def fake_register(phone, code, password):
        if phone in accounts:
            _raise("phone_taken")
        bad = _consume(phone, code)
        if bad:
            _raise(bad)
        accounts[phone] = password
        return {"ok": True, "account": {"username": phone}}

    def fake_login(login, password):
        if accounts.get(login) != password:
            _raise("bad_credentials")
        return {"ok": True, "account": {"username": login}}

    def fake_reset(phone, code, password):
        if phone not in accounts:
            _raise("unknown_account")
        bad = _consume(phone, code)
        if bad:
            _raise(bad)
        accounts[phone] = password
        return {"ok": True}

    monkeypatch.setattr(auth_api.client, "sms_send", fake_send)
    monkeypatch.setattr(auth_api.license_api, "account_register_phone", fake_register)
    monkeypatch.setattr(auth_api.license_api, "account_login_password", fake_login)
    monkeypatch.setattr(auth_api.license_api, "account_password_reset", fake_reset)
    monkeypatch.setattr(auth_api.license_api, "account_user",
                        lambda: {"username": "u", "display": "u", "entitlement": None})
    return TestClient(server.app)


def test_api_cloud_register_login_reset(remote_client):
    """云路径主流程：发码 → 注册（服务器内部校验 code，即刻登录）→ 登录 → 找回密码 → 新密码登录。"""
    c = remote_client
    code = _post(c, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]
    assert code == "654321"

    r = _post(c, "/api/register", phone=P1, code=code, password=PWD)
    assert r.status_code == 200 and r.json()["ok"]
    assert r.json()["logged_in"] is True, "云注册即下发凭据，前端应直接进主界面"

    assert _post(c, "/api/login", phone=P1, password=PWD).status_code == 200

    code2 = _post(c, "/api/sms/send", phone=P1, scene="reset").json()["dev_code"]
    assert _post(c, "/api/password/reset", phone=P1, code=code2, password="NewPass9").json()["ok"]
    assert _post(c, "/api/login", phone=P1, password="NewPass9").status_code == 200
    assert _post(c, "/api/login", phone=P1, password=PWD).status_code == 401   # 旧密码失效


def test_api_cloud_maps_errors_to_chinese(remote_client):
    c = remote_client
    code = _post(c, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]
    _post(c, "/api/register", phone=P1, code=code, password=PWD)

    # 服务端 phone_taken → 中文
    code2 = _post(c, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]
    dup = _post(c, "/api/register", phone=P1, code=code2, password=PWD)
    assert dup.status_code == 400 and dup.json()["detail"] == "该手机号已注册，请直接登录"

    # 服务端 bad_code → 中文
    _post(c, "/api/sms/send", phone=P2, scene="register")
    bad = _post(c, "/api/register", phone=P2, code="000000", password=PWD)
    assert bad.status_code == 400 and bad.json()["detail"] == "验证码错误"

    # 服务端 bad_credentials → 401 中文
    wrong = _post(c, "/api/login", phone=P1, password="WrongPass9")
    assert wrong.status_code == 401 and wrong.json()["detail"] == "手机号或密码错误"


def test_cloud_sms_send_does_not_consult_local_account_db(remote_client):
    """回归：云模式下账号在服务器，本机库是空的——发码不得用本机存在性判场景。

    旧行为：precheck_sms 查本机 phone_exists →
      · reset 场景恒报「该手机号未注册」→ 云账号用户永远无法找回密码；
      · register 场景对云端已存在的号误放行（无害，由服务端 phone_taken 兜底）。
    """
    c = remote_client
    # 本机库里从来没有 P2，reset 场景仍须放行发码（存在性交服务端判）
    assert _post(c, "/api/sms/send", phone=P2, scene="reset").status_code == 200

    # 云端已注册的号，register 场景发码也不该被本机拦（服务端 phone_taken 才是权威）
    code = _post(c, "/api/sms/send", phone=P1, scene="register").json()["dev_code"]
    _post(c, "/api/register", phone=P1, code=code, password=PWD)
    assert _post(c, "/api/sms/send", phone=P1, scene="register").status_code == 200

    # 格式非法仍须本机拦下（省一条无谓短信）
    assert _post(c, "/api/sms/send", phone="123", scene="register").status_code == 400


def test_gateway_raw_error_code_reads_as_sms_failed(remote_client, monkeypatch):
    """回归：线上 sms.py 把短信网关原始码（UNKNOWN/isv.xxx）当 reason 抛出，
    不得落到「操作失败」这类无信息文案——用户需要知道「短信没发出去」。"""
    import account_errors
    import auth_api
    c = remote_client
    monkeypatch.setattr(auth_api.client, "sms_send",
                        lambda phone: {"ok": False, "reason": "isv.MOBILE_NUMBER_ILLEGAL"})

    r = _post(c, "/api/sms/send", phone=P1, scene="register")

    assert r.status_code == 503
    assert r.json()["detail"] == account_errors.msg("sms_failed")
    assert r.json()["detail"] != account_errors.msg("__unknown__")


# ---------------------------------------------------------------------------
# 回归：服务端端点缺失/网关错误，绝不能伪装成「验证码错误」
# （2026-07-08 线上 /account/sms/verify 返 404 {"detail":"Not Found"}，
#  旧 _post 直接 return r.json()，调用方 `v.get("reason") or "bad_code"`
#  把它读成 bad_code → 用户输入正确验证码却被告知「验证码错误」。）
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is _NO_JSON:
            raise ValueError("not json")
        return self._payload


_NO_JSON = object()


@pytest.mark.parametrize("status_code,payload", [
    (404, {"detail": "Not Found"}),      # 端点未部署
    (500, {"detail": "boom"}),           # 服务端异常
    (502, _NO_JSON),                     # 网关吐 HTML
])
def test_post_treats_non_business_response_as_unavailable(monkeypatch, status_code, payload):
    from licensing import client
    monkeypatch.setattr(client.requests, "post", lambda *a, **k: _Resp(status_code, payload))

    out = client._post("/account/sms/verify", {"phone": "13800138000", "code": "123456"})

    assert out["ok"] is False
    assert out["reason"] == "unavailable", "端点缺失/网关错误必须报 unavailable，不得降级为 bad_code"


def test_post_passes_through_real_business_failure(monkeypatch):
    """带 ok 字段的业务响应原样透传——502 也不例外（服务端已表态）。"""
    from licensing import client
    monkeypatch.setattr(client.requests, "post",
                        lambda *a, **k: _Resp(502, {"ok": False, "reason": "cooldown"}))

    assert client._post("/account/sms/send", {})["reason"] == "cooldown"


# 原 test_verify_code_surfaces_unavailable_not_bad_code 已移除：其测试的
# client.sms_verify 远程校验路径系不可达死代码（线上无 /account/sms/verify 端点，
# _verify_code 只在 GF_SMS_LOCAL=1 本机模式被调用），已随清理一并删除。
# 「服务不可用绝不冒充业务失败」原则由 licensing/tests/test_client.py 的 _post ok 字段用例守护。


# ---------------------------------------------------------------------------
# 回归：single 模式下 /api/me 必须承认本机 sid 会话，否则 auth-guard 死循环
# （2026-07-08 去掉 auth-guard 的 singleMode 豁免后暴露：/api/me 只查云账号 cred，
#  本机 /api/login 建的 sid 会话被无视 → 登录成功却仍返 single:true → 反复弹窗。）
# ---------------------------------------------------------------------------
def _register_and_login(client, phone=P1, pwd=PWD):
    code = _post(client, "/api/sms/send", phone=phone, scene="register").json()["dev_code"]
    assert _post(client, "/api/register", phone=phone, code=code, password=pwd).status_code == 200
    return _post(client, "/api/login", phone=phone, password=pwd)


def test_me_is_single_before_login(client):
    """未登录：single=true，前端据此弹出登录窗。"""
    assert client.get("/api/me").json()["single"] is True


def test_me_recognizes_local_password_session(client):
    """本机手机号+密码登录后：/api/me 认这个 sid，single=false，前端放行。"""
    assert _register_and_login(client).status_code == 200

    me = client.get("/api/me").json()
    assert me["single"] is False, "登录成功却仍报 single:true → auth-guard 会再次弹窗（死循环）"
    assert me["username"] == P1


def test_logout_returns_to_login_gate(client):
    """登出后回到未登录态：single 复位为 true，登录窗重新弹出。"""
    _register_and_login(client)
    assert client.get("/api/me").json()["single"] is False

    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").json()["single"] is True


def test_session_cookie_is_persistent_for_auto_login(client):
    """免登录：sid 是持久 cookie（max-age=30天），关掉 App 再开仍是登录态。"""
    resp = _register_and_login(client)
    set_cookie = resp.headers.get("set-cookie", "")

    assert "Max-Age=" in set_cookie, "sid 必须是持久 cookie，否则关窗即掉线、无法免登录"
    max_age = int(set_cookie.split("Max-Age=")[1].split(";")[0])
    assert max_age == 30 * 24 * 3600

    # 模拟「重开 App」：沿用磁盘上的会话，仅重建请求客户端
    import server
    fresh = TestClient(server.app)
    fresh.cookies.set("sid", client.cookies["sid"])
    assert fresh.get("/api/me").json()["single"] is False
