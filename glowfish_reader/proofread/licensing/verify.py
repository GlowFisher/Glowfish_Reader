# -*- coding: utf-8 -*-
"""校验服务器签发的账号凭据（服务器公钥）。激活码令牌校验已随授权码退役删除。"""
from licensing import keys
from licensing.envelope import open_signed


def verify_cred(code: str, typ: str = None):
    """校验服务器签的凭据（trial/activation）；typ 给定则附加校验 typ。"""
    p = open_signed(code, keys.SERVER_PUB)
    if not p:
        return None
    if typ and p.get("typ") != typ:
        return None
    return p
