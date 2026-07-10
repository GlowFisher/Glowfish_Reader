# -*- coding: utf-8 -*-
"""可插拔短信验证码发送器。

后端由环境变量 GF_SMS_BACKEND 选择：
  · console（默认）——把验证码写入服务端日志/stdout，供本机内网与开发期使用；
  · aliyun         ——阿里云短信（待开通 RAM AK / 签名 / 模板后启用，未配置自动退回 console）。

GF_SMS_DEV=1 时，/api/sms/send 会在响应里回显验证码，便于开发与自动化验收；
生产环境务必不要设置该变量。发送器与鉴权内核解耦：auth.issue_sms_code 只调用 send()。
"""
import os
import logging

log = logging.getLogger("gf.sms")


def dev_mode():
    """是否开发回显模式（接口回显验证码）。"""
    return os.environ.get("GF_SMS_DEV", "") == "1"


def send(phone, code, scene):
    """发送验证码。失败只记录、不抛出（验证码已落库，用户可重试/开发期看日志）。"""
    backend = os.environ.get("GF_SMS_BACKEND", "console").strip().lower()
    if backend == "aliyun":
        try:
            _send_aliyun(phone, code, scene)
            return
        except Exception as e:                       # 未配置或调用失败 → 退回 console，避免静默失败
            log.warning("aliyun 短信发送失败，退回 console：%s", e)
    _send_console(phone, code, scene)


def _send_console(phone, code, scene):
    log.warning("[SMS:%s] to=%s code=%s", scene, phone, code)
    print(f"[SMS:{scene}] to={phone} code={code}", flush=True)


def _send_aliyun(phone, code, scene):
    """阿里云短信占位实现。

    对接点位（开通后填入）：
      环境变量 GF_ALIYUN_AK_ID / GF_ALIYUN_AK_SECRET / GF_ALIYUN_SIGN / GF_ALIYUN_TPL_CODE。
      调用 dysmsapi SendSms（HMAC-SHA1 签名，纯 stdlib 或官方 SDK 均可），
      模板参数 {"code": code}。当前未实现，抛出以触发 send() 退回 console。
    """
    if not os.environ.get("GF_ALIYUN_AK_ID"):
        raise RuntimeError("阿里云短信未配置")
    raise NotImplementedError("阿里云短信发送待接入")
