# -*- coding: utf-8 -*-
"""内置 SERVER_PUB 必须与线上服务器实际签名私钥配对。

2026-07-08 事故：线上换过 SERVER_PRIV，客户端 keys.SERVER_PUB 没回填。
表现极具迷惑性——密码校验在服务端明明通过（返 ok:true + cred），客户端
verify_cred 却验不过签名，_save_account_response 返 bad_account_cred，
用户只看到「账号凭证校验失败」，改多少次密码都没用。

离线单测无法覆盖（需要真服务器签一次名），故只在 GF_LIVE=1 时跑；
发版前 / 换服务器密钥后必须跑一次：
    GF_LIVE=1 pytest licensing/tests/test_server_pub_pairs_with_live.py
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("GF_LIVE") != "1",
    reason="需要真实账号服务器；设 GF_LIVE=1 且提供 GF_LIVE_PHONE/GF_LIVE_PASSWORD 后运行")


def test_live_login_cred_verifies_with_embedded_pubkey():
    from licensing import client, fingerprint, verify

    phone = os.environ.get("GF_LIVE_PHONE", "")
    password = os.environ.get("GF_LIVE_PASSWORD", "")
    if not phone or not password:
        pytest.skip("缺少 GF_LIVE_PHONE / GF_LIVE_PASSWORD")

    r = client.account_login_password(phone, password, fingerprint.machine_fingerprint(), "")
    assert r.get("ok"), "服务器拒绝登录：%s" % r.get("reason")

    payload = verify.verify_cred(r["cred"], "account")
    assert payload, (
        "cred 签名验不过：内置 keys.SERVER_PUB 与线上 SERVER_PRIV 不配对。"
        "在服务器上执行 python -c \"import os,sign;print(sign.pub_from_priv(os.environ['SERVER_PRIV']))\" "
        "把输出回填到 licensing/keys.py")
    assert payload.get("session_id") == r.get("session_id")
