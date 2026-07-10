# -*- coding: utf-8 -*-
"""内置公钥与服务器地址。公钥已由 keygen 回填（对应私钥在 license_server/_keys/，勿入库）。

DEFAULT_SERVER 已设为正式授权服务器域名；联调/换地域临时改指用环境变量
SHUPAI_LICENSE_SERVER 覆盖（如指向香港机公网 IP+端口）。"""
import os

# 服务器响应公钥（验 cred）。必须与线上 /etc/glowfish/account.env 的 SERVER_PRIV 配对：
# 2026-07-08 发现内置的是旧密钥对，线上换过 SERVER_PRIV 却没回填客户端 → 云登录/注册
# 密码校验明明通过，_save_account_response 却在 verify_cred 处返 bad_account_cred，
# 用户只看到「账号凭证校验失败，请重新登录」，怎么改密码都进不去。
# 校验方式：服务器上 `python -c "import os,sign;print(sign.pub_from_priv(os.environ['SERVER_PRIV']))"`。
SERVER_PUB = "SgB6Jz++3kEp61eNI3g8wUv4mELNvMPRPJXKbwC6PAQ="
DEFAULT_SERVER = "https://license.glowfishreader.com"          # 正式授权服务器（香港机免备案）


def server_url() -> str:
    return os.environ.get("SHUPAI_LICENSE_SERVER") or DEFAULT_SERVER
