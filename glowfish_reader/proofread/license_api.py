# -*- coding: utf-8 -*-
"""本机账号 API（手机号/短信登录）。授权码门禁已移除，仅保留账号能力供 auth_api 调用。"""
import time
from fastapi import HTTPException

import account_errors
import appconfig
from licensing import fingerprint, verify, store, client


def _raise(reason):
    """账号服务器 reason → 中文 HTTPException（状态码按语义分流）。"""
    raise HTTPException(account_errors.status(reason), account_errors.msg(reason))


# 免登录三闸：登录一次后凭据长期有效，但
#   1) 每次 /api/me 至多每 _PROBE_INTERVAL 秒静默联网核对一次（刷新会员状态、顺延云端会话）；
#   2) 断网宽限 OFFLINE_GRACE：距上次成功核对（签名内 checked_at，改本机文件无效）超 14 天须联网；
#   3) 签名内 expires_at 已过 → 断网也不放行（否则「到期」对长期离线用户就是幌子）。
OFFLINE_GRACE = 14 * 86400
_PROBE_INTERVAL = 300     # 每 5 分钟静默联网核对一次（封禁即时生效）
_NET_RETRY = 60           # 网络失败不烧整个节流窗：最多 60 秒后即可重试
_last_probe_ts = 0.0
_login_counted = False    # 本进程是否已被服务端计过一次登录（手动登录或首个探测）


def _refresh_from_server():
    """到点则静默核对云端会话；返回最新 store 内容。

    网络不通/服务不可用 → 不动本机凭据，交给宽限闸（60 秒后可重试）；
    服务器明确拒绝（session_expired/expired/disabled…）→ 清本机凭据、
    记下拒绝原因（account_block_reason，供 /api/me 带到期提示），强制重新登录。"""
    global _last_probe_ts, _login_counted
    d = store.load(_path())
    sid = d.get("account_session_id")
    if not sid or time.time() - _last_probe_ts < _PROBE_INTERVAL:
        return d
    _last_probe_ts = time.time()
    r = client.account_check(sid, fingerprint.machine_fingerprint(), _app_version(),
                             count_login=not _login_counted)
    if r.get("ok"):
        if _save_account_response(r).get("ok"):
            return store.load(_path())
        return d      # 响应签名不对：视同没刷新成，由宽限闸兜底
    if r.get("reason") in ("network", "unavailable"):
        _last_probe_ts = time.time() - _PROBE_INTERVAL + _NET_RETRY
        return d
    _clear_account(r.get("reason"))
    return store.load(_path())


def _clear_account(block_reason=None):
    """清空本机账号凭据（登出/被服务器拒绝共用）。block_reason 供 /api/me 带提示。"""
    store.save(_path(), {"account_cred": None, "account_session_id": None, "account": None,
                         "account_block_reason": block_reason})


def _path():
    return str(appconfig.data_root() / "license.json")


def _app_version():
    try:
        from _version import VERSION
        return VERSION
    except Exception:
        return ""


def _verify_account_cred(cred, session_id=None):
    payload = verify.verify_cred(cred, "account") if cred else None
    if not payload:
        return None
    if session_id and payload.get("session_id") != session_id:
        return None
    return payload


def _entitlement_from_account(account):
    if not isinstance(account, dict):
        return None
    status = account.get("status")
    if status == "trial":
        return {"mode": "trial", "expires_at": account.get("expires_at")}
    if status == "member":
        return {"mode": "member", "expires_at": account.get("expires_at")}
    if status in ("expired", "disabled"):
        return {"mode": status, "expires_at": account.get("expires_at")}
    return None


def _save_account_response(r):
    global _last_probe_ts, _login_counted
    if not r.get("ok"):
        return r
    session_id = r.get("session_id") or (r.get("account") or {}).get("session_id")
    payload = _verify_account_cred(r.get("cred"), session_id)
    if not payload:
        return {"ok": False, "reason": "bad_account_cred"}
    account = dict(r.get("account") or {})
    if not account.get("username"):
        account["username"] = payload.get("username")
    store.save(_path(), {
        "account_cred": r.get("cred"),
        "account_session_id": session_id,
        "account": account,
        "account_block_reason": None,
    })
    # 播种单调钟：登录/核对成功即记下当前时间与服务器 checked_at 的最大值，
    # 之后把系统时钟往回调也无法重开宽限（account_gate 取历史最大时间参与比较）。
    store.bump_seen(_path(), max(int(time.time()), int(payload.get("checked_at") or 0)))
    _last_probe_ts = time.time()      # 刚联过网（登录/核对），/api/me 不必再立即探测
    _login_counted = True             # 这次接触已被服务端记账（登录端点或带 count_login 的核对）
    return {"ok": True, "session_id": session_id, "account": account}


def account_gate():
    """账号门禁单一裁决点。返回 (user, notice)：user=None 即不放行，
    notice 是需要在登录窗展示的中文提示（目前仅「使用期限已到期」）。"""
    d = _refresh_from_server()
    session_id = d.get("account_session_id")
    account = d.get("account") if isinstance(d.get("account"), dict) else {}
    payload = _verify_account_cred(d.get("account_cred"), session_id)
    if not payload or not account:
        reason = d.get("account_block_reason")
        return None, (account_errors.msg(reason) if reason == "expired" else None)
    checked_at = int(payload.get("checked_at") or 0)
    # 防时钟回拨：now 取「本机时间 / 签名内服务器核对时间 / 历史见过的最大时间」三者最大，
    # 并经 store.bump_seen 持久化——把系统时钟往回调无法重开宽限或复活已到期的会员。
    now = store.bump_seen(_path(), max(int(time.time()), checked_at))
    exp = payload.get("expires_at")
    if exp and now > int(exp):
        return None, account_errors.msg("expired")      # 签名内使用期限已过：断网也不放行
    if now - checked_at > OFFLINE_GRACE:
        return None, None      # 离线超过宽限期：须联网核对（联网后下次 /api/me 自动恢复）
    return {
        "id": account.get("user_id") or account.get("username"),
        "username": account.get("username"),
        "display": account.get("display") or account.get("username"),
        "entitlement": _entitlement_from_account(account),
    }, None


def account_user():
    return account_gate()[0]


def account_status():
    d = store.load(_path())
    account = d.get("account") if isinstance(d.get("account"), dict) else {}
    ent = _entitlement_from_account(account)
    status = account.get("status") or "not_logged_in"
    allowed = status in ("trial", "member")
    if not allowed and status == "not_logged_in":
        return {"state": "not_logged_in", "allowed": False, "reason": "not_logged_in"}
    return {"state": status, "allowed": allowed, "account": account, "entitlement": ent}


def sms_send(phone):
    r = client.sms_send(phone)
    if not r.get("ok"):
        raise HTTPException(400, r.get("reason") or "request failed")
    return r


def account_register_phone(phone, code, password):
    """云注册：验证码交服务器内部校验（core.sms_verify），成功即下发 session_id + cred。"""
    fp = fingerprint.machine_fingerprint()
    r = client.account_register_phone(phone, code, password, fp, _app_version())
    saved = _save_account_response(r)
    if not saved.get("ok"):
        _raise(saved.get("reason"))
    return saved


def account_login_password(login, password):
    fp = fingerprint.machine_fingerprint()
    r = client.account_login_password(login, password, fp, _app_version())
    saved = _save_account_response(r)
    if not saved.get("ok"):
        _raise(saved.get("reason"))
    return saved


def account_password_reset(phone, code, password):
    """云改密：验证码交服务器内部校验；不下发 cred（前端回登录视图）。"""
    r = client.account_password_reset(phone, code, password)
    if not r.get("ok"):
        _raise(r.get("reason"))
    return {"ok": True}


def account_check():
    d = store.load(_path())
    sid = d.get("account_session_id")
    if not sid:
        raise HTTPException(401, "not_logged_in")
    r = client.account_check(sid, fingerprint.machine_fingerprint(), _app_version())
    saved = _save_account_response(r)
    if not saved.get("ok"):
        raise HTTPException(401, saved.get("reason", "request failed"))
    return saved


def account_logout():
    d = store.load(_path())
    sid = d.get("account_session_id")
    if sid:
        client.account_logout(sid)
    _clear_account()
    return {"ok": True}


