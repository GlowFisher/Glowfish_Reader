# -*- coding: utf-8 -*-
"""手机号+短信验证码登录 自测（纯 stdlib + pynacl，无需 httpx/pytest）。

在 license_server/ 目录下运行：
    python tests/test_phone_login.py
覆盖：发码→验证码登录（新号自动 7 天试用）、cred 验真、复登不重复送试用、
防刷（冷却/日限/连错锁定/过期）。全程 SMS_PROVIDER=console 不真发短信。
"""
import asyncio
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")               # 免 Windows GBK 乱码
except Exception:
    pass

# 顶层 import 前先备好环境：临时 DB + console 短信 + 现生成的服务器私钥
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nacl.signing import SigningKey                       # noqa: E402

_sk = SigningKey.generate()
os.environ["SERVER_PRIV"] = base64.b64encode(bytes(_sk)).decode()
os.environ["SMS_PROVIDER"] = "console"
_tmpdb = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["LICENSE_DB"] = _tmpdb

import core, sign                                          # noqa: E402
import serverapp                                           # noqa: E402

DAY = 86400
_captured = {}


def _fake_sms(phone, code):
    _captured["phone"], _captured["code"] = phone, code
    return {"ok": True, "reason": ""}


serverapp.sms.send_code = _fake_sms                        # 捕获验证码，不真发


class FakeReq:
    def __init__(self, data):
        self._d = data

    async def json(self):
        return self._d


def call(coro):
    """执行端点协程，把 dict / JSONResponse 统一成 (status, data)。"""
    res = asyncio.run(coro)
    if isinstance(res, dict):
        return 200, res
    return res.status_code, json.loads(res.body)


def ok(cond, msg):
    if not cond:
        raise AssertionError("FAIL: " + msg)
    print("  ok:", msg)


def main():
    pub = sign.pub_from_priv(os.environ["SERVER_PRIV"])
    phone = "13800138000"

    # 1) 发码
    st, r = call(serverapp.account_sms_send(FakeReq({"phone": phone})))
    ok(st == 200 and r.get("ok"), "发码成功")
    code = _captured["code"]
    ok(len(code) == 6 and code.isdigit(), "验证码 6 位数字")

    # 2) 错误验证码被拒
    st, r = call(serverapp.account_login_phone(FakeReq({"phone": phone, "code": "000000"})))
    ok(not r.get("ok") and r.get("reason") in ("bad_code", "too_many_attempts"), "错码被拒")

    # 3) 正确验证码登录 → 新号自动 7 天试用 + cred 验真
    st, r = call(serverapp.account_login_phone(
        FakeReq({"phone": phone, "code": code, "fingerprint": "t", "app_version": "test"})))
    ok(r.get("ok"), "验证码登录成功")
    acc = r["account"]
    ok(acc["status"] == "trial", "新号状态 trial")
    ok(abs(acc["trial_expires_at"] - (int(time.time()) + 7 * DAY)) < 120, "试用约 7 天")
    payload = sign.verify_cred(r["cred"], pub, "account")
    ok(payload and payload.get("username") == phone, "cred 验签通过且字段齐全")
    uid = acc["user_id"]

    # 4) 验证码单次有效：复用同码再登被拒
    st, r = call(serverapp.account_login_phone(FakeReq({"phone": phone, "code": code})))
    ok(not r.get("ok"), "验证码单次有效（复用被拒）")

    # 5) 复登不重复送试用（同号命中同一 user_id、试用不变）
    conn = sqlite3.connect(_tmpdb); core.init_db(conn); now = int(time.time())
    r2 = core.login_or_register_phone(conn, phone, now=now)
    ok(r2["user_id"] == uid and r2["status"] == "trial", "复登命中同一账号、仍 trial")

    # 6) 换新号 → 新账号 + 新 7 天
    r3 = core.login_or_register_phone(conn, "13900139000", now=now)
    ok(r3["user_id"] != uid and r3["status"] == "trial", "新号建新账号并开试用")

    # 7) 防刷·冷却：刚发过码，立即再发被冷却
    st, r = call(serverapp.account_sms_send(FakeReq({"phone": phone})))
    ok(st == 429 and r.get("reason") == "cooldown", "冷却拦截二次发码")

    # 8) 防刷·日限（core 层可控 now）：超过 SMS_DAILY_LIMIT 后拒
    p2 = "13700137000"
    base = int(time.time())
    for i in range(serverapp.SMS_DAILY_LIMIT):
        core.sms_issue(conn, p2, f"{i:06d}", now=base + i * 61)   # 跨冷却
    can, reason, _ = core.sms_can_send(conn, p2, base + 999, cooldown=60,
                                       daily_limit=serverapp.SMS_DAILY_LIMIT)
    ok(not can and reason == "daily_limit", "单日发码上限拦截")

    # 9) 防刷·过期：TTL 后验证码失效
    core.sms_issue(conn, "13600136000", "123456", now=base, ttl=300)
    v = core.sms_verify(conn, "13600136000", "123456", now=base + 301)
    ok(not v.get("ok") and v.get("reason") == "code_expired", "验证码过期被拒")

    # 10) 防刷·连错锁定
    core.sms_issue(conn, "13500135000", "654321", now=base, ttl=300)
    for _ in range(5):
        core.sms_verify(conn, "13500135000", "000000", now=base + 1)
    v = core.sms_verify(conn, "13500135000", "654321", now=base + 1)
    ok(not v.get("ok") and v.get("reason") == "too_many_attempts", "连错 5 次锁定")

    # 11) 验证专用端点 /account/sms/verify：发码→错码→对码消费→复用被拒
    #     （供客户端本机密码账号在注册/找回时中转校验，短信 AK 全留服务端）
    pv = "13611136111"
    st, r = call(serverapp.account_sms_send(FakeReq({"phone": pv})))
    ok(st == 200 and r.get("ok"), "verify 用例发码成功")
    vcode = _captured["code"]
    st, r = call(serverapp.account_sms_verify(FakeReq({"phone": pv, "code": "000000"})))
    ok(not r.get("ok") and r.get("reason") == "bad_code", "verify 错码被拒")
    st, r = call(serverapp.account_sms_verify(FakeReq({"phone": pv, "code": vcode})))
    ok(r.get("ok"), "verify 正确码通过")
    st, r = call(serverapp.account_sms_verify(FakeReq({"phone": pv, "code": vcode})))
    ok(not r.get("ok"), "verify 单次消费（复用被拒）")

    print("\nALL PASS")


if __name__ == "__main__":
    main()
