import sqlite3

import core

DAY = 86400


def db():
    c = sqlite3.connect(":memory:")
    core.init_db(c)
    return c


def test_register_creates_7_day_trial():
    c = db()
    r = core.create_account(c, "alice", "secret1", now=1000, trial_days=7)
    assert r["ok"]
    assert r["status"] == "trial"
    assert r["trial_expires_at"] == 1000 + 7 * DAY
    assert r["allowed"] is True


def test_login_and_check_session():
    c = db()
    user = core.create_account(c, "alice", "secret1", now=1000)
    login = core.verify_account_password(c, "alice", "secret1", now=1001)
    assert login["ok"]
    sess = core.create_account_session(c, user["user_id"], now=1001, fingerprint="fp")
    checked = core.check_account_session(c, sess["session_id"], now=1002, fingerprint="fp")
    assert checked["ok"] and checked["username"] == "alice"


def test_disable_blocks_next_check():
    c = db()
    user = core.create_account(c, "alice", "secret1", now=1000)
    sess = core.create_account_session(c, user["user_id"], now=1001)
    core.admin_set_disabled(c, user["user_id"], True, now=1002)
    checked = core.check_account_session(c, sess["session_id"], now=1003)
    assert checked["ok"] is False
    assert checked["reason"] == "disabled"


def test_admin_renew_turns_expired_trial_active():
    c = db()
    user = core.create_account(c, "alice", "secret1", now=1000, trial_days=1)
    assert core.account_info(c, user["user_id"], now=1000 + 2 * DAY)["status"] == "expired"
    renewed = core.admin_renew_account(c, user["user_id"], days=365, now=1000 + 2 * DAY)
    assert renewed["status"] == "member"      # 现行状态口径：trial/member/expired/disabled
    assert renewed["subscription_expires_at"] == 1000 + 367 * DAY


def test_usage_summary_accumulates_without_content_fields():
    c = db()
    user = core.create_account(c, "alice", "secret1", now=1000)
    sess = core.create_account_session(c, user["user_id"], now=1001)
    core.record_account_usage(c, sess["session_id"], now=1002, counts={"ocr_count": 2, "export_count": 1})
    usage = core.usage_for_user(c, user["user_id"])
    assert usage["ocr_count"] == 2
    assert usage["export_count"] == 1
