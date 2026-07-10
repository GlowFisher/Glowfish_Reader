# -*- coding: utf-8 -*-
"""Ed25519 签名信封：base64url(json({"d":payload,"s":sig_b64}))。客户端只验签（公钥）。"""
import json, base64, sys
from pathlib import Path
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

_BASE = Path(__file__).resolve().parents[1]
_ROOT = _BASE.parent if _BASE.name == "proofread" else _BASE
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from license_common.signing import canonical_json_bytes


def _canon(d: dict) -> bytes:
    return canonical_json_bytes(d)


def open_signed(code: str, pub_b64: str):
    """验签拆信封：成功返回 payload dict，任何不合法返回 None（不抛）。"""
    try:
        raw = base64.urlsafe_b64decode(code.encode())
        obj = json.loads(raw)
        payload, sig = obj["d"], base64.b64decode(obj["s"])
        VerifyKey(base64.b64decode(pub_b64)).verify(_canon(payload), sig)
        return payload
    except (ValueError, KeyError, BadSignatureError, TypeError):
        return None
