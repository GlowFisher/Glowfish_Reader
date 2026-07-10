# -*- coding: utf-8 -*-
"""一次性生成服务器响应签名用 Ed25519 密钥对。私钥写 _keys/（gitignore）。"""
import sys, base64
from pathlib import Path
from nacl.signing import SigningKey
sys.stdout.reconfigure(encoding="utf-8")


def gen():
    sk = SigningKey.generate()
    return base64.b64encode(bytes(sk)).decode(), base64.b64encode(bytes(sk.verify_key)).decode()


if __name__ == "__main__":
    keys_dir = Path(__file__).resolve().parent / "_keys"
    keys_dir.mkdir(exist_ok=True)
    srv_priv, srv_pub = gen()
    (keys_dir / "server_private.b64").write_text(srv_priv, encoding="utf-8")
    (keys_dir / "public_keys.txt").write_text(f"SERVER_PUB={srv_pub}\n", encoding="utf-8")
    print("生成完毕 -> _keys/。SERVER_PRIV 环境变量取 server_private.b64 内容：")
    print(f"SERVER_PUB = \"{srv_pub}\"")
