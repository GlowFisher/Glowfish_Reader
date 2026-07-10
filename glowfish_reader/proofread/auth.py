# -*- coding: utf-8 -*-
"""用户认证内核：SQLite 用户库 + 会话 token + pbkdf2 密码哈希（纯标准库，零第三方依赖）。

单机/内网多用户：开放注册；会话 token 存库、以 httponly cookie 下发。
用户库在 _work/_sys/users.db，与各用户史料数据（_work/users/<uid>/）物理分离。
"""
import re
import time
import hmac
import sqlite3
import secrets
import hashlib
import threading

import appconfig

# 用户库随数据根走（仅 multi 模式使用；single 模式 current_user 不触此处，库不会被建）。
SYS_DIR = appconfig.data_root() / "_sys"
DB_PATH = SYS_DIR / "users.db"

SESSION_TTL = 30 * 24 * 3600        # 会话有效期 30 天
PBKDF2_ROUNDS = 200_000             # 密码哈希迭代次数
# 用户名：2-32 位，字母/数字/下划线/连字符/点/中文
_UNAME_RE = re.compile(r"^[\w.\-一-龥]{2,32}$", re.UNICODE)
# 手机号：11 位，1 开头、次位 3-9
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
# 密码：≥6 位，数字与大小写字母（不强制混合）
_PWD_RE = re.compile(r"^[A-Za-z0-9]{6,}$")

SMS_TTL = 5 * 60            # 验证码有效期 5 分钟
SMS_RESEND = 60            # 同号重发间隔 60 秒
_SMS_SCENES = ("register", "reset")

_lock = threading.Lock()
_conn = None


class AuthError(Exception):
    """注册/登录的可读错误（直接回前端展示）。"""


def _db():
    global _conn
    if _conn is None:
        SYS_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display TEXT,
                pw_hash TEXT NOT NULL,
                pw_salt TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions(
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sms_codes(
                phone TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                code_salt TEXT NOT NULL,
                scene TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                sent_at INTEGER NOT NULL
            );
            """
        )
        # 幂等迁移：为旧库 users 补 phone 列（SQLite UNIQUE 允许多个 NULL，旧账号不受影响）
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(users)").fetchall()}
        if "phone" not in cols:
            _conn.execute("ALTER TABLE users ADD COLUMN phone TEXT")
            _conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
        _conn.commit()
    return _conn


def _hash_pw(password, salt=None):
    """pbkdf2-sha256 派生；salt 为十六进制串。返回 (hash_hex, salt_hex)。"""
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                             bytes.fromhex(salt), PBKDF2_ROUNDS)
    return dk.hex(), salt


def create_user(username, password, display=None):
    """注册新用户。校验不过 / 重名 抛 AuthError。返回用户公开信息 dict。"""
    username = (username or "").strip()
    if not _UNAME_RE.match(username):
        raise AuthError("用户名须为 2-32 位字母/数字/下划线/中文")
    if len(password or "") < 6:
        raise AuthError("密码至少 6 位")
    h, salt = _hash_pw(password)
    now = int(time.time())
    with _lock:
        db = _db()
        try:
            cur = db.execute(
                "INSERT INTO users(username,display,pw_hash,pw_salt,created_at) "
                "VALUES(?,?,?,?,?)", (username, display or username, h, salt, now))
            db.commit()
        except sqlite3.IntegrityError:
            raise AuthError("用户名已被注册")
    return {"id": cur.lastrowid, "username": username, "display": display or username}


def verify_user(username, password):
    """校验账号密码；成功返回用户公开信息 dict，失败返回 None。"""
    username = (username or "").strip()
    with _lock:
        row = _db().execute(
            "SELECT id,username,display,pw_hash,pw_salt FROM users WHERE username=?",
            (username,)).fetchone()
    if not row:
        return None
    h, _ = _hash_pw(password, row[4])
    if not hmac.compare_digest(h, row[3]):        # 定时安全比较
        return None
    return {"id": row[0], "username": row[1], "display": row[2]}


def create_session(user_id):
    """新建会话，返回 token。"""
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _lock:
        db = _db()
        db.execute(
            "INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
            (token, int(user_id), now, now + SESSION_TTL))
        db.commit()
    return token


def get_session_user(token):
    """token → 用户公开信息 dict；无效/过期返回 None（过期顺手清理）。"""
    if not token:
        return None
    now = int(time.time())
    with _lock:
        row = _db().execute(
            "SELECT u.id,u.username,u.display,s.expires_at FROM sessions s "
            "JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
    if not row:
        return None
    if row[3] < now:
        delete_session(token)
        return None
    return {"id": row[0], "username": row[1], "display": row[2]}


def delete_session(token):
    if not token:
        return
    with _lock:
        db = _db()
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        db.commit()


# ============================ 手机号 + 短信验证码 ============================

def _check_phone(phone):
    phone = (phone or "").strip()
    if not _PHONE_RE.match(phone):
        raise AuthError("手机号格式不正确")
    return phone


def _check_password(password):
    if not _PWD_RE.match(password or ""):
        raise AuthError("密码至少 6 位，仅限数字与大小写字母")


def validate_credentials(phone, password):
    """只做手机号/密码的格式预校验：不落库、不消费验证码。不合格抛 AuthError。

    供 auth_api 在校验短信验证码（一次性消费）**之前**调用——否则格式错误会白白
    烧掉一条验证码，用户改完密码还得重新等一条短信。"""
    _check_phone(phone)
    _check_password(password)


def phone_exists(phone):
    phone = (phone or "").strip()
    with _lock:
        row = _db().execute("SELECT 1 FROM users WHERE phone=?", (phone,)).fetchone()
    return row is not None


def precheck_sms(phone, scene, check_exists=True):
    """发码前本地前置校验：手机号格式 + 场景合法性（+ 可选的本机存在性）。

    真实发码走远程服务器（短信 AK 只在服务端），本机不生成验证码；此校验先于远程调用，
    省一次无谓短信并给出可读中文提示。校验不过抛 AuthError。返回规范化后的 phone。

    ⚠check_exists 仅在「本机账号库即事实源」时才可为 True（GF_SMS_LOCAL=1 兜底模式）。
    云账号模式下账号存在于服务器，本机库是空的：register 会误放行、reset 会误报
    「该手机号未注册」导致永远无法找回密码。存在性一律交服务端判定。"""
    phone = _check_phone(phone)
    if scene not in _SMS_SCENES:
        raise AuthError("非法的验证码场景")
    if not check_exists:
        return phone
    exists = phone_exists(phone)
    if scene == "register" and exists:
        raise AuthError("该手机号已注册，请直接登录")
    if scene == "reset" and not exists:
        raise AuthError("该手机号未注册")
    return phone


def issue_sms_code(phone, scene):
    """签发验证码：校验手机号/场景 + 60s 重发节流，落 hash，交发送器发出。返回明文 code。

    register 场景要求手机号未注册；reset 场景要求手机号已注册。"""
    import sms
    phone = _check_phone(phone)
    if scene not in _SMS_SCENES:
        raise AuthError("非法的验证码场景")
    exists = phone_exists(phone)
    if scene == "register" and exists:
        raise AuthError("该手机号已注册，请直接登录")
    if scene == "reset" and not exists:
        raise AuthError("该手机号未注册")
    now = int(time.time())
    with _lock:
        db = _db()
        row = db.execute("SELECT sent_at FROM sms_codes WHERE phone=?", (phone,)).fetchone()
        if row and now - int(row[0]) < SMS_RESEND:
            raise AuthError("验证码发送过于频繁，请稍后再试")
        code = "".join(secrets.choice("0123456789") for _ in range(6))
        h, salt = _hash_pw(code)
        db.execute("REPLACE INTO sms_codes(phone,code_hash,code_salt,scene,expires_at,sent_at) "
                   "VALUES(?,?,?,?,?,?)", (phone, h, salt, scene, now + SMS_TTL, now))
        db.commit()
    sms.send(phone, code, scene)              # 发送失败由发送器内部处理/记录
    return code


def verify_sms_code(phone, scene, code):
    """校验并消费验证码：场景匹配、未过期、hash 相符即返回 True 并删除该行；否则 False。"""
    phone = (phone or "").strip()
    now = int(time.time())
    with _lock:
        db = _db()
        row = db.execute("SELECT code_hash,code_salt,scene,expires_at FROM sms_codes WHERE phone=?",
                         (phone,)).fetchone()
        if not row:
            return False
        code_hash, code_salt, row_scene, expires_at = row
        if row_scene != scene or expires_at < now:
            return False
        h, _ = _hash_pw(code or "", code_salt)
        if not hmac.compare_digest(h, code_hash):
            return False
        db.execute("DELETE FROM sms_codes WHERE phone=?", (phone,))   # 一次性消费
        db.commit()
    return True


def create_user_by_phone(phone, password):
    """手机号注册。手机号已注册 / 校验不过 抛 AuthError。返回用户公开信息 dict。"""
    phone = _check_phone(phone)
    _check_password(password)
    h, salt = _hash_pw(password)
    now = int(time.time())
    with _lock:
        db = _db()
        try:
            cur = db.execute(
                "INSERT INTO users(username,display,pw_hash,pw_salt,created_at,phone) "
                "VALUES(?,?,?,?,?,?)", (phone, phone, h, salt, now, phone))
            db.commit()
        except sqlite3.IntegrityError:
            raise AuthError("该手机号已注册")
    return {"id": cur.lastrowid, "username": phone, "display": phone}


def verify_user_by_phone(phone, password):
    """手机号+密码登录；成功返回用户公开信息 dict，失败返回 None。"""
    phone = (phone or "").strip()
    with _lock:
        row = _db().execute(
            "SELECT id,username,display,pw_hash,pw_salt FROM users WHERE phone=?",
            (phone,)).fetchone()
    if not row:
        return None
    h, _ = _hash_pw(password, row[4])
    if not hmac.compare_digest(h, row[3]):
        return None
    return {"id": row[0], "username": row[1], "display": row[2]}


def reset_password_by_phone(phone, password):
    """按手机号重置密码。手机号未注册 / 校验不过 抛 AuthError。"""
    phone = _check_phone(phone)
    _check_password(password)
    h, salt = _hash_pw(password)
    with _lock:
        db = _db()
        cur = db.execute("UPDATE users SET pw_hash=?,pw_salt=? WHERE phone=?", (h, salt, phone))
        db.commit()
    if cur.rowcount == 0:
        raise AuthError("该手机号未注册")


def user_count():
    with _lock:
        return _db().execute("SELECT COUNT(*) FROM users").fetchone()[0]

