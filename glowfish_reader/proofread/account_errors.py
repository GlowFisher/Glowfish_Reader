# -*- coding: utf-8 -*-
"""账号服务器 reason（英文错误码）→ 用户可读中文 + HTTP 状态码。

单一事实源：错误码集合取自线上 account-server 的 core.py/sms.py。
license_api 与 auth_api 共用本模块（放独立文件避免循环 import）。

⚠未知 reason 一律回退到「操作失败」，绝不能猜成某个具体业务失败——
2026-07-08 的线上事故正是「端点不存在」被兜底成 bad_code，用户看到「验证码错误」。
"""

MESSAGES = {
    # 验证码
    "bad_code": "验证码错误",
    "code_expired": "验证码已过期，请重新获取",
    "too_many_attempts": "验证码尝试次数过多，请重新获取",
    "sms_failed": "短信发送失败，请稍后重试",
    "sms_not_configured": "短信服务尚未配置，请联系管理员",
    "cooldown": "验证码发送过于频繁，请稍后再试",
    "daily_limit": "今日验证码发送次数已达上限，请明天再试",
    # 手机号 / 账号
    "bad_phone": "手机号格式不正确",
    "phone_taken": "该手机号已注册，请直接登录",
    "username_taken": "该用户名已被占用",
    "bad_username": "用户名格式不正确",
    "unknown_account": "该账号不存在",
    "bad_credentials": "手机号或密码错误",
    "weak_password": "密码太弱，请用 6 位以上数字/字母",
    "disabled": "该账号已被停用",
    # 会话 / 授权
    "not_logged_in": "尚未登录",
    "session_expired": "登录已过期，请重新登录",
    "expired": "您的使用期限已到期，可前往 http://glowfishreader.com 找管理员续期",
    "not_activated": "尚未激活",
    "revoked": "授权已被回收",
    "seat_full": "该账号的设备数已达上限",
    "unknown_license": "授权不存在",
    "bad_account_cred": "账号凭据校验失败，请重新登录",
    # 传输层（客户端本地生成，非服务器返回）
    "network": "连不上服务器，请联网后重试",
    "unavailable": "账号服务暂不可用，请稍后重试",
}

_STATUS = {
    "cooldown": 429,
    "daily_limit": 429,
    "too_many_attempts": 429,
    "network": 503,
    "unavailable": 503,
    "sms_failed": 503,
    "sms_not_configured": 503,
    "bad_credentials": 401,
    "session_expired": 401,
    "not_logged_in": 401,
    "disabled": 403,
}


def msg(reason):
    return MESSAGES.get(reason, "操作失败，请稍后重试")


def status(reason):
    return _STATUS.get(reason, 400)
