# -*- coding: utf-8 -*-
"""账号服务器核心逻辑（SQLite）。

单文件 SQLite：账号表用于注册试用（用户名密码 / 手机号短信验证码）、
后台续期/封禁和使用汇总。这里不保存任何史料内容、文件名或路径。
"""
import hashlib
import hmac
import re
import secrets


DAY = 86400
SESSION_TTL = 30 * DAY
PBKDF2_ROUNDS = 200_000
_UNAME_RE = re.compile(r"^[\w.\-@\u4e00-\u9fff]{2,64}$", re.UNICODE)
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")           # \u4ec5\u5927\u9646\u624b\u673a\u53f7\uff1b\u56fd\u9645\u77ed\u4fe1\u672c\u671f\u4e0d\u505a


def init_db(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display TEXT,
        pw_hash TEXT NOT NULL,
        pw_salt TEXT NOT NULL,
        disabled INTEGER DEFAULT 0,
        trial_expires_at INTEGER NOT NULL,
        subscription_expires_at INTEGER DEFAULT 0,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        last_login_at INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS account_sessions(
        session_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        issued_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        last_seen INTEGER NOT NULL,
        revoked INTEGER DEFAULT 0,
        fingerprint TEXT DEFAULT '',
        app_version TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS usage_summary(
        user_id INTEGER PRIMARY KEY,
        check_count INTEGER DEFAULT 0,
        login_count INTEGER DEFAULT 0,
        import_count INTEGER DEFAULT 0,
        ocr_count INTEGER DEFAULT 0,
        export_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        usage_seconds INTEGER DEFAULT 0,
        last_event_at INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS admin_users(
        username TEXT PRIMARY KEY,
        pw_hash TEXT NOT NULL,
        pw_salt TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_sessions(
        session_id TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        issued_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sms_codes(
        phone TEXT PRIMARY KEY,          -- 每手机号只保留最近一条待验证码
        code_hash TEXT NOT NULL,         -- 验证码经 sha256(salt|code) 存储，不落明文
        code_salt TEXT NOT NULL,
        scene TEXT DEFAULT 'login',
        expires_at INTEGER NOT NULL,     -- 签发 + ttl(默认 300s)
        attempts INTEGER DEFAULT 0,      -- 校验失败累计，>= max 锁定
        last_sent_at INTEGER NOT NULL,   -- 冷却判断
        sent_today INTEGER DEFAULT 1,    -- 当日发送计数
        day_bucket INTEGER NOT NULL      -- now//86400，跨天归零
    );
    """)
    db.execute("""
    CREATE TABLE IF NOT EXISTS admin_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin TEXT NOT NULL,
        action TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        old_value TEXT DEFAULT '',
        new_value TEXT DEFAULT '',
        created_at INTEGER NOT NULL
    )
    """)
    # 旧库迁移：accounts 加手机号列（可空，仅手机号注册的账号有值）+ 部分唯一索引
    acols = {r[1] for r in db.execute("PRAGMA table_info(accounts)").fetchall()}
    if "phone" not in acols:
        db.execute("ALTER TABLE accounts ADD COLUMN phone TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_accounts_phone "
               "ON accounts(phone) WHERE phone IS NOT NULL")
    db.commit()


def _hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                             bytes.fromhex(salt), PBKDF2_ROUNDS)
    return dk.hex(), salt


def _valid_username(username):
    return bool(_UNAME_RE.match((username or "").strip()))


def _account_status(row, now):
    user_id, username, display, disabled, trial_exp, sub_exp, created, last_login = row
    if disabled:
        status, tier, exp = "disabled", None, None
    elif sub_exp and now <= sub_exp:
        status, tier, exp = "member", "member", sub_exp
    elif now <= trial_exp:
        status, tier, exp = "trial", "trial", trial_exp
    else:
        status, tier, exp = "expired", None, max(trial_exp or 0, sub_exp or 0)
    return {
        "user_id": user_id,
        "username": username,
        "display": display or username,
        "disabled": bool(disabled),
        "status": status,
        "tier": tier,
        "expires_at": exp,
        "trial_expires_at": trial_exp,
        "subscription_expires_at": sub_exp or 0,
        "created_at": created,
        "last_login_at": last_login or 0,
        "allowed": status in ("trial", "member"),
    }


def _account_by_username(db, username):
    return db.execute(
        "SELECT id,username,display,pw_hash,pw_salt,disabled,trial_expires_at,"
        "subscription_expires_at,created_at,last_login_at FROM accounts WHERE username=?",
        ((username or "").strip(),)).fetchone()


def _account_by_id(db, user_id):
    return db.execute(
        "SELECT id,username,display,disabled,trial_expires_at,subscription_expires_at,"
        "created_at,last_login_at FROM accounts WHERE id=?", (int(user_id),)).fetchone()


def create_account(db, username, password, now, trial_days=14):
    username = (username or "").strip()
    if not _valid_username(username):
        return {"ok": False, "reason": "bad_username"}
    if len(password or "") < 6:
        return {"ok": False, "reason": "weak_password"}
    if _account_by_username(db, username):
        return {"ok": False, "reason": "username_taken"}
    h, salt = _hash_pw(password)
    exp = now + int(trial_days) * DAY
    cur = db.execute(
        "INSERT INTO accounts(username,display,pw_hash,pw_salt,trial_expires_at,"
        "subscription_expires_at,created_at,updated_at,last_login_at) VALUES(?,?,?,?,?,?,?,?,0)",
        (username, username, h, salt, exp, 0, now, now))
    db.commit()
    return {"ok": True, **account_info(db, cur.lastrowid, now)}


def _valid_phone(phone):
    return bool(_PHONE_RE.match((phone or "").strip()))


def _account_by_phone(db, phone):
    return db.execute(
        "SELECT id,username,display,disabled,trial_expires_at,subscription_expires_at,"
        "created_at,last_login_at FROM accounts WHERE phone=?", ((phone or "").strip(),)).fetchone()


def _account_login_by_phone(db, phone):
    return db.execute(
        "SELECT id,username,display,pw_hash,pw_salt,disabled,trial_expires_at,"
        "subscription_expires_at,created_at,last_login_at FROM accounts WHERE phone=?",
        ((phone or "").strip(),)).fetchone()


def create_phone_account(db, phone, now, trial_days=14):
    """手机号注册：username=phone、phone=phone，密码设为不可用随机哈希（禁止密码登进手机账号）。"""
    phone = (phone or "").strip()
    if not _valid_phone(phone):
        return {"ok": False, "reason": "bad_phone"}
    if _account_by_phone(db, phone) or _account_by_username(db, phone):
        return {"ok": False, "reason": "phone_taken"}
    h, salt = _hash_pw(secrets.token_hex(16))       # 随机不可用密码
    exp = now + int(trial_days) * DAY
    cur = db.execute(
        "INSERT INTO accounts(username,display,pw_hash,pw_salt,phone,trial_expires_at,"
        "subscription_expires_at,created_at,updated_at,last_login_at) VALUES(?,?,?,?,?,?,?,?,?,0)",
        (phone, phone, h, salt, phone, exp, 0, now, now))
    db.commit()
    return {"ok": True, **account_info(db, cur.lastrowid, now)}


def register_phone_account(db, phone, code, password, now, trial_days=14):
    """短信验证通过后注册手机号账号，默认送 14 天试用（trial_days 可覆盖）。"""
    phone = (phone or "").strip()
    if not _valid_phone(phone):
        return {"ok": False, "reason": "bad_phone"}
    if len(password or "") < 6:
        return {"ok": False, "reason": "weak_password"}
    if _account_by_phone(db, phone) or _account_by_username(db, phone):
        return {"ok": False, "reason": "phone_taken"}
    v = sms_verify(db, phone, code, now=now)
    if not v.get("ok"):
        return v
    h, salt = _hash_pw(password)
    exp = now + int(trial_days) * DAY
    cur = db.execute(
        "INSERT INTO accounts(username,display,pw_hash,pw_salt,phone,trial_expires_at,"
        "subscription_expires_at,created_at,updated_at,last_login_at) VALUES(?,?,?,?,?,?,?,?,?,0)",
        (phone, phone, h, salt, phone, exp, 0, now, now))
    db.commit()
    info = account_info(db, cur.lastrowid, now)
    info["phone"] = phone
    return {"ok": True, **info}


def login_or_register_phone(db, phone, now, trial_days=14):
    """验证码已核验后调用：手机号有账号则返回状态，无则建号并开 7 天试用。"""
    phone = (phone or "").strip()
    if not _valid_phone(phone):
        return {"ok": False, "reason": "bad_phone"}
    row = _account_by_phone(db, phone)
    if not row:
        r = create_phone_account(db, phone, now, trial_days=trial_days)
        if not r.get("ok"):
            return r
        return {"ok": True, **account_info(db, r["user_id"], now)}
    info = _account_status(row, now)
    if info["status"] == "disabled":
        return {"ok": False, "reason": "disabled", **info}
    return {"ok": True, **info}


def verify_account_password(db, username, password, now):
    login = (username or "").strip()
    row = _account_login_by_phone(db, login) if _valid_phone(login) else None
    if not row:
        row = _account_by_username(db, login)
    if not row:
        return {"ok": False, "reason": "bad_credentials"}
    user_id, uname, display, pw_hash, pw_salt, disabled, trial_exp, sub_exp, created, last_login = row
    h, _ = _hash_pw(password, pw_salt)
    if not hmac.compare_digest(h, pw_hash):
        return {"ok": False, "reason": "bad_credentials"}
    info = _account_status((user_id, uname, display, disabled, trial_exp, sub_exp, created, last_login), now)
    if info["status"] == "disabled":
        return {"ok": False, "reason": "disabled", **info}
    return {"ok": True, **info}


def account_info(db, user_id, now):
    row = _account_by_id(db, user_id)
    if not row:
        return {"ok": False, "reason": "unknown_account"}
    return _account_status(row, now)


def create_account_session(db, user_id, now, fingerprint="", app_version=""):
    sid = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO account_sessions(session_id,user_id,issued_at,expires_at,last_seen,"
        "revoked,fingerprint,app_version) VALUES(?,?,?,?,?,?,?,?)",
        (sid, int(user_id), now, now + SESSION_TTL, now, 0, fingerprint or "", app_version or ""))
    db.execute("UPDATE accounts SET last_login_at=?, updated_at=? WHERE id=?", (now, now, int(user_id)))
    _inc_usage(db, int(user_id), now, {"login_count": 1})
    db.commit()
    info = account_info(db, user_id, now)
    return {"ok": True, "session_id": sid, **info}


def check_account_session(db, session_id, now, session_seconds=0, fingerprint="", app_version="",
                          count_login=False):
    """核对会话。成功即把会话到期顺延 SESSION_TTL（滑动续期）：活跃用户永不重登，
    闲置超 30 天才需重新输密码。count_login=True（客户端启动静默核对）计一次登录并刷新
    last_login_at；内部调用（如用量上报）保持默认 False，不虚增登录数。"""
    if not session_id:
        return {"ok": False, "reason": "not_logged_in"}
    row = db.execute(
        "SELECT user_id,expires_at,revoked FROM account_sessions WHERE session_id=?",
        (session_id,)).fetchone()
    if not row:
        return {"ok": False, "reason": "not_logged_in"}
    user_id, sess_exp, revoked = row
    if revoked or now > sess_exp:
        return {"ok": False, "reason": "session_expired"}
    info = account_info(db, user_id, now)
    if info.get("status") == "disabled":
        return {"ok": False, "reason": "disabled", **info}
    if not info.get("allowed"):
        return {"ok": False, "reason": info.get("status", "blocked"), **info}
    db.execute("UPDATE account_sessions SET last_seen=?, expires_at=?, fingerprint=?, app_version=?"
               " WHERE session_id=?",
               (now, now + SESSION_TTL, fingerprint or "", app_version or "", session_id))
    counts = {
        "check_count": 1,
        "usage_seconds": _clamp_int(session_seconds, 0, DAY),
    }
    if count_login:
        counts["login_count"] = 1
        db.execute("UPDATE accounts SET last_login_at=?, updated_at=? WHERE id=?",
                   (now, now, int(user_id)))
    _inc_usage(db, int(user_id), now, counts)
    db.commit()
    return {"ok": True, "session_id": session_id, "checked_at": now, **info}


def revoke_account_session(db, session_id):
    db.execute("UPDATE account_sessions SET revoked=1 WHERE session_id=?", (session_id,))
    db.commit()
    return {"ok": True}


def _clamp_int(v, lo=0, hi=1000000):
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(n, hi))


def _inc_usage(db, user_id, now, counts):
    fields = {
        "check_count": _clamp_int(counts.get("check_count"), 0, 1000),
        "login_count": _clamp_int(counts.get("login_count"), 0, 1000),
        "import_count": _clamp_int(counts.get("import_count"), 0, 1000),
        "ocr_count": _clamp_int(counts.get("ocr_count"), 0, 1000),
        "export_count": _clamp_int(counts.get("export_count"), 0, 1000),
        "error_count": _clamp_int(counts.get("error_count"), 0, 1000),
        "usage_seconds": _clamp_int(counts.get("usage_seconds"), 0, DAY),
    }
    db.execute(
        "INSERT INTO usage_summary(user_id,check_count,login_count,import_count,ocr_count,"
        "export_count,error_count,usage_seconds,last_event_at) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "check_count=check_count+excluded.check_count,"
        "login_count=login_count+excluded.login_count,"
        "import_count=import_count+excluded.import_count,"
        "ocr_count=ocr_count+excluded.ocr_count,"
        "export_count=export_count+excluded.export_count,"
        "error_count=error_count+excluded.error_count,"
        "usage_seconds=usage_seconds+excluded.usage_seconds,"
        "last_event_at=excluded.last_event_at",
        (int(user_id), fields["check_count"], fields["login_count"], fields["import_count"],
         fields["ocr_count"], fields["export_count"], fields["error_count"],
         fields["usage_seconds"], now))


def record_account_usage(db, session_id, now, counts):
    checked = check_account_session(db, session_id, now)
    if not checked.get("ok"):
        return checked
    _inc_usage(db, int(checked["user_id"]), now, counts or {})
    db.commit()
    return {"ok": True}


def usage_for_user(db, user_id):
    row = db.execute(
        "SELECT check_count,login_count,import_count,ocr_count,export_count,error_count,"
        "usage_seconds,last_event_at FROM usage_summary WHERE user_id=?", (int(user_id),)).fetchone()
    if not row:
        return {"check_count": 0, "login_count": 0, "import_count": 0, "ocr_count": 0,
                "export_count": 0, "error_count": 0, "usage_seconds": 0, "last_event_at": 0}
    keys = ("check_count", "login_count", "import_count", "ocr_count", "export_count",
            "error_count", "usage_seconds", "last_event_at")
    return dict(zip(keys, row))


# ---- 短信验证码存取 + 防刷（真金白银，阈值即短信费上闸） -------------------

def _hash_code(code, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.sha256((salt + "|" + (code or "")).encode("utf-8")).hexdigest()
    return h, salt


def sms_can_send(db, phone, now, cooldown=60, daily_limit=5):
    """发码前置校验：距上次发送须 >= cooldown 秒，且当日发送数 < daily_limit。
    返回 (ok, reason, retry_after)。"""
    phone = (phone or "").strip()
    if not _valid_phone(phone):
        return (False, "bad_phone", 0)
    row = db.execute("SELECT last_sent_at,sent_today,day_bucket FROM sms_codes WHERE phone=?",
                     (phone,)).fetchone()
    if not row:
        return (True, "", 0)
    last_sent, sent_today, day_bucket = row
    wait = cooldown - (now - int(last_sent or 0))
    if wait > 0:
        return (False, "cooldown", wait)
    if int(day_bucket or 0) == now // DAY and int(sent_today or 0) >= daily_limit:
        return (False, "daily_limit", 0)
    return (True, "", 0)


def sms_issue(db, phone, code, now, ttl=300):
    """签发验证码：哈希落库、重置 attempts、更新发送计数（跨天归零）。"""
    phone = (phone or "").strip()
    h, salt = _hash_code(code)
    today = now // DAY
    row = db.execute("SELECT sent_today,day_bucket FROM sms_codes WHERE phone=?", (phone,)).fetchone()
    sent_today = 1
    if row and int(row[1] or 0) == today:
        sent_today = int(row[0] or 0) + 1
    db.execute(
        "INSERT INTO sms_codes(phone,code_hash,code_salt,scene,expires_at,attempts,"
        "last_sent_at,sent_today,day_bucket) VALUES(?,?,?,?,?,0,?,?,?) "
        "ON CONFLICT(phone) DO UPDATE SET code_hash=excluded.code_hash,code_salt=excluded.code_salt,"
        "scene=excluded.scene,expires_at=excluded.expires_at,attempts=0,"
        "last_sent_at=excluded.last_sent_at,sent_today=excluded.sent_today,day_bucket=excluded.day_bucket",
        (phone, h, salt, "login", now + int(ttl), now, sent_today, today))
    db.commit()
    return {"ok": True, "ttl": int(ttl)}


def sms_verify(db, phone, code, now, max_attempts=5):
    """校验验证码：存在/未过期/未超限/命中；成功即清空验证码（单次有效），失败累计 attempts。
    注意：只清空 code_hash 而不删整行，保留 last_sent_at/sent_today 发送节流账本——
    否则登录一次就会重置冷却与单日上限，短信费防刷失效。"""
    phone = (phone or "").strip()
    row = db.execute("SELECT code_hash,code_salt,expires_at,attempts FROM sms_codes WHERE phone=?",
                     (phone,)).fetchone()
    if not row or not row[0]:                          # 无行或验证码已被消费
        return {"ok": False, "reason": "bad_code"}
    code_hash, code_salt, expires_at, attempts = row
    if now > int(expires_at):
        return {"ok": False, "reason": "code_expired"}
    if int(attempts or 0) >= max_attempts:
        return {"ok": False, "reason": "too_many_attempts"}
    h, _ = _hash_code(code, code_salt)
    if not hmac.compare_digest(h, code_hash):
        db.execute("UPDATE sms_codes SET attempts=attempts+1 WHERE phone=?", (phone,)); db.commit()
        return {"ok": False, "reason": "bad_code"}
    db.execute("UPDATE sms_codes SET code_hash='' WHERE phone=?", (phone,)); db.commit()
    return {"ok": True}


def admin_upsert(db, username, password, now):
    username = (username or "").strip()
    if not username or len(password or "") < 8:
        return {"ok": False, "reason": "bad_admin"}
    h, salt = _hash_pw(password)
    db.execute(
        "INSERT INTO admin_users(username,pw_hash,pw_salt,created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET pw_hash=excluded.pw_hash,pw_salt=excluded.pw_salt",
        (username, h, salt, now))
    db.commit()
    return {"ok": True}


def admin_count(db):
    return db.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]


def verify_admin_password(db, username, password):
    row = db.execute("SELECT pw_hash,pw_salt FROM admin_users WHERE username=?",
                     ((username or "").strip(),)).fetchone()
    if not row:
        return {"ok": False, "reason": "bad_credentials"}
    h, _ = _hash_pw(password, row[1])
    if not hmac.compare_digest(h, row[0]):
        return {"ok": False, "reason": "bad_credentials"}
    return {"ok": True, "username": (username or "").strip()}


def create_admin_session(db, username, now):
    sid = secrets.token_urlsafe(32)
    db.execute("INSERT INTO admin_sessions(session_id,username,issued_at,expires_at) VALUES(?,?,?,?)",
               (sid, username, now, now + SESSION_TTL))
    db.commit()
    return sid


def get_admin_session(db, session_id, now):
    if not session_id:
        return None
    row = db.execute("SELECT username,expires_at FROM admin_sessions WHERE session_id=?",
                     (session_id,)).fetchone()
    if not row or row[1] < now:
        return None
    return {"username": row[0]}


def delete_admin_session(db, session_id):
    if session_id:
        db.execute("DELETE FROM admin_sessions WHERE session_id=?", (session_id,))
        db.commit()


def admin_list_accounts(db, now, q="", limit=200):
    q = (q or "").strip()
    params = []
    where = ""
    if q:
        where = "WHERE username LIKE ? OR display LIKE ? OR phone LIKE ?"
        params = [f"%{q}%", f"%{q}%", f"%{q}%"]
    rows = db.execute(
        "SELECT id,username,display,disabled,trial_expires_at,subscription_expires_at,"
        "created_at,last_login_at,phone FROM accounts " + where + " ORDER BY id DESC LIMIT ?",
        (*params, int(limit))).fetchall()
    out = []
    for row in rows:
        info = _account_status(row[:8], now)        # _account_status 只解包前 8 列
        info["phone"] = row[8]
        info["usage"] = usage_for_user(db, info["user_id"])
        out.append(info)
    return out


def admin_get_account(db, user_id, now):
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    prow = db.execute("SELECT phone FROM accounts WHERE id=?", (int(user_id),)).fetchone()
    info["phone"] = prow[0] if prow else None
    info["usage"] = usage_for_user(db, user_id)
    sessions = db.execute(
        "SELECT issued_at,expires_at,last_seen,revoked,fingerprint,app_version "
        "FROM account_sessions WHERE user_id=? ORDER BY last_seen DESC LIMIT 20",
        (int(user_id),)).fetchall()
    info["sessions"] = [
        {"issued_at": r[0], "expires_at": r[1], "last_seen": r[2], "revoked": bool(r[3]),
         "fingerprint": r[4], "app_version": r[5]} for r in sessions
    ]
    return info


def _audit(db, admin, action, user_id, old_value, new_value, now):
    db.execute(
        "INSERT INTO admin_audit(admin,action,user_id,old_value,new_value,created_at) "
        "VALUES(?,?,?,?,?,?)",
        (admin or "system", action, int(user_id), str(old_value or ""), str(new_value or ""), now))


def admin_set_disabled(db, user_id, disabled, now, admin="system"):
    old = account_info(db, user_id, now).get("disabled")
    db.execute("UPDATE accounts SET disabled=?, updated_at=? WHERE id=?",
               (1 if disabled else 0, now, int(user_id)))
    _audit(db, admin, "set_disabled", user_id, old, bool(disabled), now)
    db.commit()
    return account_info(db, user_id, now)


def admin_extend_membership(db, user_id, days, now, admin="system"):
    days = max(1, min(int(days or 365), 3650))
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    old = int(info.get("subscription_expires_at") or 0)
    base = max(now, old)
    exp = base + days * DAY
    db.execute("UPDATE accounts SET subscription_expires_at=?, disabled=0, updated_at=? WHERE id=?",
               (exp, now, int(user_id)))
    _audit(db, admin, "extend_membership", user_id, old, exp, now)
    db.commit()
    return account_info(db, user_id, now)


def admin_extend_active_expiry(db, user_id, days, now, admin="system"):
    """增/减使用期限天数，只延展当前生效的到期字段，不改变会员/试用档位。

    days>0 增加，days<0 暂不支持（现阶段无法减少天数，clamp 到最少 1 天）。
    """
    days = max(1, min(int(days or 0), 3650))
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    field = "subscription_expires_at" if info["status"] == "member" else "trial_expires_at"
    old = int(info.get(field) or 0)
    base = max(now, old)
    exp = base + days * DAY
    db.execute(f"UPDATE accounts SET {field}=?, updated_at=? WHERE id=?",
               (exp, now, int(user_id)))
    _audit(db, admin, "extend_active_expiry:%s" % field, user_id, old, exp, now)
    db.commit()
    return account_info(db, user_id, now)


def admin_reset_to_trial(db, user_id, now, admin="system", days=7):
    """把账号使用权限强制重置为「试用 days 天，从今天算」，无视当前到期时间/会员状态。"""
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    old = "%s/%s" % (int(info.get("trial_expires_at") or 0), int(info.get("subscription_expires_at") or 0))
    new_trial = now + int(days) * DAY
    db.execute("UPDATE accounts SET trial_expires_at=?, subscription_expires_at=0, updated_at=? WHERE id=?",
               (new_trial, now, int(user_id)))
    _audit(db, admin, "reset_to_trial", user_id, old, new_trial, now)
    db.commit()
    return account_info(db, user_id, now)


def admin_set_membership(db, user_id, is_member, now, admin="system"):
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    old = int(info.get("subscription_expires_at") or 0)
    new_exp = (now + 365 * DAY) if is_member else 0
    db.execute("UPDATE accounts SET subscription_expires_at=?, updated_at=? WHERE id=?",
               (new_exp, now, int(user_id)))
    _audit(db, admin, "set_membership", user_id, old, new_exp, now)
    db.commit()
    return account_info(db, user_id, now)


def admin_extend_trial(db, user_id, days, now, admin="system"):
    days = max(1, min(int(days or 7), 3650))
    info = account_info(db, user_id, now)
    if not info.get("user_id"):
        return info
    old = int(info.get("trial_expires_at") or 0)
    base = max(now, old)
    exp = base + days * DAY
    db.execute("UPDATE accounts SET trial_expires_at=?, disabled=0, updated_at=? WHERE id=?",
               (exp, now, int(user_id)))
    _audit(db, admin, "extend_trial", user_id, old, exp, now)
    db.commit()
    return account_info(db, user_id, now)


def admin_renew_account(db, user_id, days, now):
    return admin_extend_membership(db, user_id, days, now)


def admin_reset_password(db, user_id, password, now, admin="system"):
    if len(password or "") < 6:
        return {"ok": False, "reason": "weak_password"}
    h, salt = _hash_pw(password)
    db.execute("UPDATE accounts SET pw_hash=?, pw_salt=?, updated_at=? WHERE id=?",
               (h, salt, now, int(user_id)))
    _audit(db, admin, "reset_password", user_id, "", "changed", now)
    db.commit()
    return {"ok": True}


def reset_account_password(db, phone, code, password, now):
    """SMS-verified password reset for phone accounts. Returns account info on success."""
    phone = (phone or "").strip()
    if not _valid_phone(phone):
        return {"ok": False, "reason": "bad_phone"}
    v = sms_verify(db, phone, code, now=now)
    if not v.get("ok"):
        return v
    row = _account_login_by_phone(db, phone)
    if not row:
        return {"ok": False, "reason": "unknown_account"}
    if len(password or "") < 6:
        return {"ok": False, "reason": "weak_password"}
    user_id = row[0]
    h, salt = _hash_pw(password)
    db.execute("UPDATE accounts SET pw_hash=?, pw_salt=?, updated_at=? WHERE id=?",
               (h, salt, now, int(user_id)))
    db.commit()
    info = account_info(db, user_id, now)
    info["phone"] = phone
    return {"ok": True, **info}


def admin_stats(db, now):
    """Return aggregate account statistics for admin dashboard."""
    rows = db.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN disabled=0 AND (subscription_expires_at>=?1 OR trial_expires_at>=?1)
                THEN 1 ELSE 0 END) AS active,
            SUM(CASE WHEN disabled=1 THEN 1 ELSE 0 END) AS disabled_count
        FROM accounts
    """, (now,)).fetchone()
    return {"total": rows[0] or 0, "active": rows[1] or 0, "disabled": rows[2] or 0}


# ---- Notice / Announcement file-based CRUD ----

import json as _json
import os as _os

_NOTICE_PATH = _os.environ.get("NOTICE_JSON_PATH", "/opt/glowfish/account-server/notices.json")


def _read_notices():
    try:
        with open(_NOTICE_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            data = {"schema": 1, "updated_at": "", "notices": []}
    except (FileNotFoundError, _json.JSONDecodeError):
        data = {"schema": 1, "updated_at": "", "notices": []}
    if not isinstance(data.get("notices"), list):
        data["notices"] = []
    return data


def _write_notices(data):
    _os.makedirs(_os.path.dirname(_NOTICE_PATH), exist_ok=True)
    with open(_NOTICE_PATH, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


def notice_list():
    data = _read_notices()
    return data.get("notices", [])


def notice_get(notice_id):
    notices = notice_list()
    for n in notices:
        if n.get("id") == notice_id:
            return n
    return None


def notice_save(notice, now_iso):
    """Create or update a notice. Returns the saved notice dict."""
    data = _read_notices()
    notices = data["notices"]
    nid = notice.get("id", "").strip()
    found = False
    for i, n in enumerate(notices):
        if n.get("id") == nid:
            notices[i] = notice
            found = True
            break
    if not found:
        notices.insert(0, notice)
    data["updated_at"] = now_iso
    data["notices"] = notices
    _write_notices(data)
    return notice


def notice_delete(notice_id):
    data = _read_notices()
    data["notices"] = [n for n in data["notices"] if n.get("id") != notice_id]
    data["updated_at"] = ""
    _write_notices(data)
    return True

