# -*- coding: utf-8 -*-
"""联授权服务器：短超时、失败软返回。cred 真伪由调用方 verify_cred 校验。"""
import requests
from licensing import keys

_TIMEOUT = 6


def _post(path, body):
    """POST 授权服务器。任何非业务响应统一降级为 {ok:False, reason:...}。

    ⚠不能直接 return r.json()：服务端 404/500 时 FastAPI 返回 {"detail": "..."}，
    该字典没有 ok/reason，调用方 `v.get("reason") or "bad_code"` 会把「端点不存在」
    误报成「验证码错误」。故此处要求响应必须是带 ok 字段的业务 JSON，否则判为 unavailable。"""
    try:
        r = requests.post(keys.server_url() + path, json=body, timeout=_TIMEOUT)
    except Exception:
        return {"ok": False, "reason": "network"}
    try:
        data = r.json()
    except ValueError:
        data = None
    if not isinstance(data, dict) or "ok" not in data:
        # 端点缺失/网关错误/非 JSON：服务不可用，绝不冒充业务失败
        return {"ok": False, "reason": "unavailable", "http_status": r.status_code}
    return data


def sms_send(phone):
    return _post("/account/sms/send", {"phone": phone, "scene": "login"})


def account_password_reset(phone, code, password):
    """手机号 + 验证码 重置密码（服务端内部校验 code）。返回 {ok} 或 {ok:False, reason}。"""
    return _post("/account/password/reset", {"phone": phone, "code": code, "password": password})


def account_register_phone(phone, code, password, fp, app_version=""):
    return _post("/account/register/phone", {
        "phone": phone, "code": code, "password": password,
        "fingerprint": fp, "app_version": app_version or "",
    })


def account_login_password(login, password, fp, app_version=""):
    return _post("/account/login/password", {
        "login": login, "password": password,
        "fingerprint": fp, "app_version": app_version or "",
    })


def account_check(session_id, fp, app_version="", session_seconds=0, count_login=False):
    """count_login=True 仅在「App 冷启动的首个静默核对」传：服务端将其计为一次自动登录。"""
    return _post("/account/check", {
        "session_id": session_id, "fingerprint": fp,
        "app_version": app_version or "", "session_seconds": session_seconds or 0,
        "count_login": bool(count_login),
    })


def account_logout(session_id):
    return _post("/account/logout", {"session_id": session_id})

