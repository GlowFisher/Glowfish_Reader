# -*- coding: utf-8 -*-
"""认证 API：注册 / 登录 / 登出 / 当前用户。会话以 httponly cookie(sid) 维持。

单机/内网部署：开放注册（供他人各自建号使用）；http 内网无法用 Secure cookie，
故 cookie 用 httponly + SameSite=Lax，边界由「绑定主机 + 会话 token」守。
"""
import os

from fastapi import APIRouter, Request, Response, HTTPException, Cookie, Depends

import account_errors
import appconfig
import auth
import license_api
import sms
from licensing import client
from userctx import COOKIE, current_user

router = APIRouter()


def _set_cookie(resp: Response, token: str):
    resp.set_cookie(COOKIE, token, max_age=auth.SESSION_TTL,
                    httponly=True, samesite="lax", path="/")


def _public(user):
    payload = {"username": user["username"], "display": user["display"]}
    entitlement = user.get("entitlement") or appconfig.get_account_entitlement()
    if entitlement:
        payload["entitlement"] = entitlement
    return payload


# ---- 短信验证码：默认由云账号服务器发码（短信 AK 只在服务端）；GF_SMS_LOCAL=1 本机兜底 ----
# reason（英文）→ 中文/状态码 统一走 account_errors（单一事实源）
_sms_msg = account_errors.msg
_sms_status = account_errors.status


def _sms_local():
    """离线/开发兜底开关：本机生成验证码（仅 console 打印），不经服务器。生产勿设。

    ⚠打包态（消费者正式 exe）恒忽略该环境变量——否则用户在启动前设 GF_SMS_LOCAL=1
    即可绕开云端账号服务器、在本机自建一个永不过期的账号，白嫖付费门禁。与
    appconfig.get_mode() 对 SHUPAI_MODE 的锁法同一思路：授权相关开关不可经环境变量
    在成品 exe 里翻盘，只有源码直跑（开发态）才认。"""
    if appconfig.is_frozen():
        return False
    return os.environ.get("GF_SMS_LOCAL", "") == "1"


def _send_code(phone, scene):
    """发码：默认远程（服务器持短信 AK），GF_SMS_LOCAL=1 本机兜底。
    返回可回显的 dev_code（GF_SMS_DEV=1 时）或 None；失败抛 HTTPException（已映射中文）。"""
    try:
        if _sms_local():
            code = auth.issue_sms_code(phone, scene)      # 内部已做格式/场景/存在性/节流校验
            return code if sms.dev_mode() else None
        # ⚠云模式下账号在服务器，本机库是空的：不能用本机存在性判 register/reset，
        # 否则「找回密码」永远被误报「该手机号未注册」。只校验格式与场景。
        auth.precheck_sms(phone, scene, check_exists=False)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    r = client.sms_send(phone)
    if not r.get("ok"):
        reason = r.get("reason") or "sms_failed"
        # ⚠线上 sms.py 直接把短信网关原始错误码当 reason 抛出（UNKNOWN / isv.MOBILE_NUMBER_ILLEGAL …）。
        # 这类码永远不在 account_errors 表内，若走默认「操作失败」会掩盖「短信没发出去」这一事实。
        if reason not in account_errors.MESSAGES:
            reason = "sms_failed"
        raise HTTPException(_sms_status(reason), _sms_msg(reason))
    return r.get("dev_code") if sms.dev_mode() else None


def _verify_code(phone, scene, code):
    """校验验证码（仅 GF_SMS_LOCAL=1 本机兜底模式会走到这里；
    云模式下验证码随注册/改密请求交服务端内部校验，不经本函数）。"""
    if not auth.verify_sms_code(phone, scene, code):
        raise HTTPException(400, "验证码错误或已过期")


@router.post("/api/sms/send")
async def sms_send(req: Request):
    """发送短信验证码。入参 {phone, scene:"register"|"reset"}。
    默认由香港机服务器发码（短信 AK 只在服务端）；dev 模式（GF_SMS_DEV=1）回显 dev_code。"""
    body = await req.json()
    dev_code = _send_code((body.get("phone") or "").strip(), (body.get("scene") or "").strip())
    out = {"ok": True}
    if dev_code is not None:
        out["dev_code"] = dev_code
    return out


@router.post("/api/register/phone")
async def register_phone(req: Request):
    body = await req.json()
    return license_api.account_register_phone(body.get("phone"), body.get("code"), body.get("password"))


@router.post("/api/login/password")
async def login_password(req: Request):
    body = await req.json()
    login = body.get("login") or body.get("username") or body.get("phone")
    return license_api.account_login_password(login, body.get("password"))


@router.post("/api/register")
async def register(req: Request):
    """手机号 + 验证码注册。入参 {phone, code, password}。

    云模式（默认）：验证码与账号都在服务器，POST /account/register/phone 内部校验 code 并
    下发 cred → 存本机 store → 视为已登录（返回 logged_in，前端直接进主界面）。
    本机模式（GF_SMS_LOCAL=1）：本机 sqlite 建号，注册不自动登录（前端回登录视图）。
    """
    body = await req.json()
    phone = (body.get("phone") or "").strip()
    # 格式预校验须在校验验证码（一次性消费）之前，否则弱密码/错手机号会白白烧掉一条验证码。
    try:
        auth.validate_credentials(phone, body.get("password"))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))

    if not _sms_local():
        license_api.account_register_phone(phone, (body.get("code") or "").strip(), body.get("password"))
        user = license_api.account_user() or {"username": phone, "display": phone}
        return {"ok": True, "user": _public(user), "logged_in": True}

    _verify_code(phone, "register", (body.get("code") or "").strip())
    try:
        user = auth.create_user_by_phone(phone, body.get("password"))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "user": _public(user)}


@router.post("/api/login")
async def login(req: Request, resp: Response):
    """手机号 + 密码登录。入参 {phone, password}。

    云模式：POST /account/login/password → cred 落本机 store，/api/me 经 account_user() 放行。
    本机模式：本机 sqlite 校验 + 下发 sid 会话 cookie（TTL 30 天，天然免登录）。
    """
    body = await req.json()
    phone = (body.get("phone") or "").strip()
    if not _sms_local():
        license_api.account_login_password(phone, body.get("password"))
        user = license_api.account_user() or {"username": phone, "display": phone}
        return {"ok": True, "user": _public(user)}

    user = auth.verify_user_by_phone(phone, body.get("password"))
    if not user:
        raise HTTPException(401, "手机号或密码错误")
    _set_cookie(resp, auth.create_session(user["id"]))
    return {"ok": True, "user": _public(user)}


@router.post("/api/password/reset")
async def password_reset(req: Request):
    """手机号 + 验证码 找回/重置密码。入参 {phone, code, password}。成功后前端回登录视图。"""
    body = await req.json()
    phone = (body.get("phone") or "").strip()
    # 同 register：先验格式，再消费验证码。
    try:
        auth.validate_credentials(phone, body.get("password"))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))

    if not _sms_local():
        # 云改密：验证码交服务器内部校验（线上无独立 /account/sms/verify 端点）
        license_api.account_password_reset(phone, (body.get("code") or "").strip(), body.get("password"))
        return {"ok": True}

    _verify_code(phone, "reset", (body.get("code") or "").strip())
    try:
        auth.reset_password_by_phone(phone, body.get("password"))
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/logout")
async def logout(resp: Response, sid: str = Cookie(default=None)):
    if appconfig.is_single():
        license_api.account_logout()
    auth.delete_session(sid)
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(user=Depends(current_user), sid: str = Cookie(default=None)):
    if appconfig.is_single():
        account, notice = license_api.account_gate()
        if account:
            return {**_public(account), "single": False}
        # 本机手机号+密码登录（/api/login 建的 sid 会话，TTL 30 天）同样算已登录。
        # ⚠没有这一支，去掉 auth-guard 的 single 豁免后会死循环：登录成功 → /api/me
        # 仍返 single:true → 再次弹登录窗。data 目录不受影响：current_user 在 single
        # 模式恒返 LOCAL_USER(uid=local)，此处只影响「是否放行 UI」。
        local_user = auth.get_session_user(sid)
        if local_user:
            return {**_public(local_user), "single": False}
        out = {**_public(user), "single": True}
        if notice:
            out["notice"] = notice      # 前端登录窗展示（如「使用期限已到期…」）
        return out
    return {**_public(user), "single": appconfig.is_single()}
