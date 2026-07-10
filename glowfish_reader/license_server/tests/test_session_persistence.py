# -*- coding: utf-8 -*-
"""免登录三件套：会话滑动续期 / 启动核对计登录 / 到期账号登录返回 expired。"""
import base64
import json
import os
import sqlite3
import sys
import tempfile
import asyncio

from nacl.signing import SigningKey

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_sk = SigningKey.generate()
os.environ.setdefault("SERVER_PRIV", base64.b64encode(bytes(_sk)).decode())
os.environ.setdefault("SMS_PROVIDER", "console")
os.environ.setdefault("LICENSE_DB", os.path.join(tempfile.mkdtemp(), "accounts.db"))

import core  # noqa: E402
import serverapp  # noqa: E402

DAY = 86400
NOW = 2_000_000_000


class FakeReq:
    def __init__(self, data):
        self._data = data

    async def json(self):
        return self._data


def call(coro):
    res = asyncio.run(coro)
    if isinstance(res, dict):
        return 200, res
    return res.status_code, json.loads(res.body)


def fresh_db():
    db = sqlite3.connect(":memory:")
    core.init_db(db)
    return db


def _trial_session(db, phone="13800138000", trial_days=400):
    """建号并登录，返回 session_id。试用期默认拉长，避免会话测试被试用到期干扰。"""
    core.sms_issue(db, phone, "123456", now=NOW, ttl=300)
    r = core.register_phone_account(db, phone, "123456", "secret1", now=NOW, trial_days=trial_days)
    assert r["ok"], r
    sess = core.create_account_session(db, r["user_id"], now=NOW)
    assert sess["ok"], sess
    return r["user_id"], sess["session_id"]


def test_check_slides_session_expiry_so_active_users_never_relogin():
    db = fresh_db()
    _, sid = _trial_session(db)

    # 第 20 天核对：应顺延会话；否则第 45 天（发session后>30天）必被踢
    assert core.check_account_session(db, sid, now=NOW + 20 * DAY)["ok"] is True
    assert core.check_account_session(db, sid, now=NOW + 45 * DAY)["ok"] is True


def test_session_still_expires_after_30_idle_days():
    db = fresh_db()
    _, sid = _trial_session(db)

    assert core.check_account_session(db, sid, now=NOW + 5 * DAY)["ok"] is True
    # 距上次核对闲置 31 天：会话过期，须重新登录
    r = core.check_account_session(db, sid, now=NOW + 5 * DAY + 31 * DAY)
    assert r["ok"] is False and r["reason"] == "session_expired"


def test_check_with_count_login_flag_records_a_login():
    db = fresh_db()
    uid, sid = _trial_session(db)
    assert core.usage_for_user(db, uid)["login_count"] == 1  # 建号登录算 1 次

    assert core.check_account_session(db, sid, now=NOW + DAY, count_login=True)["ok"] is True
    assert core.usage_for_user(db, uid)["login_count"] == 2
    assert core.account_info(db, uid, NOW + DAY)["last_login_at"] == NOW + DAY

    # 默认（用量上报等内部调用）不算登录
    assert core.check_account_session(db, sid, now=NOW + 2 * DAY)["ok"] is True
    assert core.usage_for_user(db, uid)["login_count"] == 2


def test_account_check_endpoint_counts_login_only_when_client_flags_it():
    """登录计数口径由客户端声明：仅进程首个探测带 count_login=true；无标志的心跳不计。"""
    db = fresh_db()
    old = serverapp._conn
    serverapp._conn = db
    try:
        uid, sid = _trial_session(db)
        # 无标志（每小时心跳/旧客户端）：不计登录
        _, r = call(serverapp.account_check(FakeReq({"session_id": sid})))
        assert r["ok"] is True
        assert core.usage_for_user(db, uid)["login_count"] == 1

        # 带标志（App 启动首个静默核对＝自动登录）：计一次
        _, r = call(serverapp.account_check(FakeReq({"session_id": sid, "count_login": True})))
        assert r["ok"] is True
        assert core.usage_for_user(db, uid)["login_count"] == 2
    finally:
        serverapp._conn = old


def test_login_password_endpoint_returns_expired_for_lapsed_account():
    db = fresh_db()
    old = serverapp._conn
    serverapp._conn = db
    try:
        import time as _t
        phone = "13800138001"
        # 端点内部用真实时钟，故注册时间取「真实现在 - 20 天」，试用 7 天 → 现已到期
        then = int(_t.time()) - 20 * DAY
        core.sms_issue(db, phone, "123456", now=then, ttl=300)
        r = core.register_phone_account(db, phone, "123456", "secret1", now=then, trial_days=7)
        assert r["ok"], r

        # 试用 7 天，第 20 天来登录：应明确返回 expired，而不是签出缺 session_id 的残废凭据
        _, resp = call(serverapp.account_login_password(FakeReq({
            "login": phone, "password": "secret1"})))
        assert resp.get("ok") is False
        assert resp.get("reason") == "expired"
    finally:
        serverapp._conn = old
