# -*- coding: utf-8 -*-
"""服务器签名信封（账号凭据签发/验证）。格式须与 proofread/licensing/envelope.py 一致。"""
import json, base64
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def make_signed(payload: dict, sk_b64: str) -> str:
    sk = SigningKey(base64.b64decode(sk_b64))
    sig = base64.b64encode(sk.sign(_canon(payload)).signature).decode()
    raw = json.dumps({"d": payload, "s": sig}, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode()


def pub_from_priv(sk_b64: str) -> str:
    """从私钥派生对应公钥（base64），免去单独配 SERVER_PUB 环境变量。"""
    return base64.b64encode(bytes(SigningKey(base64.b64decode(sk_b64)).verify_key)).decode()


def verify_cred(code: str, pub_b64: str, typ: str = None):
    """验证服务器自签的凭据（trial/activation）；typ 给定则附加校验。失败返回 None。"""
    try:
        obj = json.loads(base64.urlsafe_b64decode(code.encode()))
        payload, sig = obj["d"], base64.b64decode(obj["s"])
        VerifyKey(base64.b64decode(pub_b64)).verify(_canon(payload), sig)
    except (ValueError, KeyError, BadSignatureError, TypeError):
        return None
    if typ and payload.get("typ") != typ:
        return None
    return payload
