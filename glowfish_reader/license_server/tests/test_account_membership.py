# -*- coding: utf-8 -*-
import base64
import json
import os
import sqlite3
import sys
import tempfile
import time
import asyncio

from nacl.signing import SigningKey

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_sk = SigningKey.generate()
os.environ["SERVER_PRIV"] = base64.b64encode(bytes(_sk)).decode()
os.environ["SMS_PROVIDER"] = "console"
os.environ["LICENSE_DB"] = os.path.join(tempfile.mkdtemp(), "accounts.db")

import core  # noqa: E402
import serverapp  # noqa: E402
import sign  # noqa: E402

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


def issue_code(db, phone, code="123456"):
    core.sms_issue(db, phone, code, now=NOW, ttl=300)


def test_phone_registration_requires_code_and_password_then_grants_trial():
    db = fresh_db()
    phone = "13800138000"
    issue_code(db, phone)

    r = core.register_phone_account(db, phone, "123456", "secret1", now=NOW)

    assert r["ok"] is True
    assert r["phone"] == phone
    assert r["username"] == phone
    assert r["status"] == "trial"
    assert r["tier"] == "trial"
    assert r["expires_at"] == NOW + 14 * DAY      # 现行口径：注册送 14 天试用
    assert r["allowed"] is True


def test_phone_registration_rejects_duplicate_phone():
    db = fresh_db()
    phone = "13800138000"
    issue_code(db, phone, "111111")
    assert core.register_phone_account(db, phone, "111111", "secret1", now=NOW)["ok"]
    issue_code(db, phone, "222222")

    r = core.register_phone_account(db, phone, "222222", "secret1", now=NOW + 10)

    assert r == {"ok": False, "reason": "phone_taken"}


def test_password_login_accepts_phone_and_returns_member_status_over_trial():
    db = fresh_db()
    phone = "13800138000"
    issue_code(db, phone)
    created = core.register_phone_account(db, phone, "123456", "secret1", now=NOW)
    core.admin_extend_membership(db, created["user_id"], days=30, now=NOW + 100, admin="ops")

    r = core.verify_account_password(db, phone, "secret1", now=NOW + 200)

    assert r["ok"] is True
    assert r["status"] == "member"
    assert r["tier"] == "member"
    assert r["expires_at"] == NOW + 100 + 30 * DAY
    assert r["allowed"] is True


def test_admin_extend_trial_and_membership_are_audited():
    db = fresh_db()
    phone = "13800138000"
    issue_code(db, phone)
    created = core.register_phone_account(db, phone, "123456", "secret1", now=NOW)

    trial = core.admin_extend_trial(db, created["user_id"], days=3, now=NOW + 50, admin="ops")
    member = core.admin_extend_membership(db, created["user_id"], days=30, now=NOW + 60, admin="ops")

    assert trial["trial_expires_at"] == NOW + 14 * DAY + 3 * DAY      # 14 天试用 + 后台加 3 天
    assert member["status"] == "member"
    rows = db.execute(
        "SELECT admin,action,user_id,old_value,new_value FROM admin_audit ORDER BY id"
    ).fetchall()
    assert rows[0][0:3] == ("ops", "extend_trial", created["user_id"])
    assert rows[1][0:3] == ("ops", "extend_membership", created["user_id"])


def test_disabled_account_cannot_login_or_check_session():
    db = fresh_db()
    phone = "13800138000"
    issue_code(db, phone)
    created = core.register_phone_account(db, phone, "123456", "secret1", now=NOW)
    sess = core.create_account_session(db, created["user_id"], now=NOW)
    core.admin_set_disabled(db, created["user_id"], True, now=NOW + 10, admin="ops")

    login = core.verify_account_password(db, phone, "secret1", now=NOW + 11)
    checked = core.check_account_session(db, sess["session_id"], now=NOW + 11)

    assert login["ok"] is False
    assert login["reason"] == "disabled"
    assert checked["ok"] is False
    assert checked["reason"] == "disabled"


def test_server_routes_return_stable_account_credential_for_phone_registration_and_password_login():
    phone = "13900139000"
    serverapp.sms.send_code = lambda p, c: {"ok": True, "reason": ""}
    serverapp._conn.execute("DELETE FROM sms_codes")
    serverapp._conn.execute("DELETE FROM accounts")
    serverapp._conn.commit()
    captured = {}

    def fake_sms(p, code):
        captured["code"] = code
        return {"ok": True, "reason": ""}

    serverapp.sms.send_code = fake_sms
    st, sent = call(serverapp.account_sms_send(FakeReq({"phone": phone})))
    assert st == 200 and sent["ok"] is True

    st, registered = call(serverapp.account_register_phone(
        FakeReq({"phone": phone, "code": captured["code"], "password": "secret1",
                 "fingerprint": "fp", "app_version": "test"})
    ))
    assert st == 200
    assert registered["ok"] is True
    assert registered["session_id"]
    assert registered["account"]["status"] == "trial"
    payload = sign.verify_cred(registered["cred"], serverapp.SERVER_PUB, "account")
    assert payload["session_id"] == registered["session_id"]
    assert payload["status"] == "trial"

    st, logged = call(serverapp.account_login_password(
        FakeReq({"login": phone, "password": "secret1", "fingerprint": "fp"})
    ))
    assert st == 200
    assert logged["ok"] is True
    assert logged["session_id"]
