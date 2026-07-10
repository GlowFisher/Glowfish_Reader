import sys, base64
from pathlib import Path
from nacl.signing import SigningKey
import sign

# 让测试能 import 客户端 envelope，验证两侧格式对齐
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "proofread"))
from licensing import envelope

def test_make_signed_opens_with_client_envelope():
    sk = SigningKey.generate()
    sk_b64 = base64.b64encode(bytes(sk)).decode()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    code = sign.make_signed({"typ": "account", "user_id": 1}, sk_b64)
    assert envelope.open_signed(code, pub_b64) == {"typ": "account", "user_id": 1}
