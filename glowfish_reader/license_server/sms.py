# -*- coding: utf-8 -*-
"""短信网关抽象：按环境变量 SMS_PROVIDER 分发。

- console（开发默认）：只把验证码打到 stdout/日志，不真发短信，便于本地联调与自测。
- aliyun_auth（生产）：调阿里云短信认证服务 dypnsapi（免签名免模板，个人可用）。

对外只暴露 send_code(phone, code) -> {"ok": bool, "reason": str}。号码日志脱敏。
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid


def _mask(phone):
    p = (phone or "").strip()
    return (p[:3] + "****" + p[-4:]) if len(p) == 11 else "***"


def _provider():
    return (os.environ.get("SMS_PROVIDER") or "console").strip().lower()


# ---- aliyun Dysmsapi 纯 stdlib 签名 ----------------------------------------

def _percent(s):
    # 阿里云 RPC 专用百分号编码：quote 后再修正 + * ~ 三处
    return (urllib.parse.quote(str(s), safe="~")
            .replace("+", "%20").replace("*", "%2A").replace("%7E", "~"))
# ---- aliyun 短信认证服务 dypnsapi（免签名免模板，个人可用）----

def _aliyun_auth_send(phone, code):
    ak_id = os.environ.get("ALIYUN_AK_ID", "")
    ak_secret = os.environ.get("ALIYUN_AK_SECRET", "")
    if not (ak_id and ak_secret):
        return {"ok": False, "reason": "sms_not_configured"}
    params = {
        "Format": "JSON",
        "Version": "2017-05-25",
        "AccessKeyId": ak_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "Action": "SendSmsVerifyCode",
        "RegionId": "cn-hangzhou",
        "PhoneNumber": phone,
        "SignName": "恒创联众",
        "TemplateCode": "100001",
        "TemplateParam": json.dumps({"code": code, "min": "5"}, ensure_ascii=False),
    }
    canon = "&".join(f"{_percent(k)}={_percent(params[k])}" for k in sorted(params))
    string_to_sign = "GET&%2F&" + _percent(canon)
    sig = base64.b64encode(hmac.new((ak_secret + "&").encode(), string_to_sign.encode(),
                                    hashlib.sha1).digest()).decode()
    url = "https://dypnsapi.aliyuncs.com/?" + canon + "&Signature=" + _percent(sig)
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[sms] aliyun_auth send error phone={_mask(phone)}: {e}", flush=True)
        return {"ok": False, "reason": "sms_failed"}
    if body.get("Success"):
        return {"ok": True, "reason": ""}
    code = body.get("Code", "unknown")
    msg = body.get("Message", "")
    print(f"[sms] aliyun_auth reject phone={_mask(phone)}: {code} {msg}", flush=True)
    return {"ok": False, "reason": code if code else "sms_failed"}


def send_code(phone, code):
    """发送 6 位验证码。返回 {"ok": bool, "reason": str}。"""
    provider = _provider()
    if provider == "aliyun_auth":
        return _aliyun_auth_send(phone, code)
    # console：开发/自测后端，把验证码打到日志，不真发短信
    print(f"[sms:console] phone={_mask(phone)} code={code}", flush=True)
    return {"ok": True, "reason": ""}
