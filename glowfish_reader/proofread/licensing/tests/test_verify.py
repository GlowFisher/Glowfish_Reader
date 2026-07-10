import json, base64
from nacl.signing import SigningKey
from licensing import envelope

def _make_signed(payload, sk):
    msg = envelope._canon(payload)
    sig = base64.b64encode(sk.sign(msg).signature).decode()
    raw = json.dumps({"d": payload, "s": sig}, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode()

def test_open_signed_roundtrip():
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    code = _make_signed({"typ": "license", "license_id": "GF-1"}, sk)
    assert envelope.open_signed(code, pub) == {"typ": "license", "license_id": "GF-1"}

def test_open_signed_rejects_wrong_key():
    sk = SigningKey.generate(); other = SigningKey.generate()
    pub_other = base64.b64encode(bytes(other.verify_key)).decode()
    code = _make_signed({"typ": "license"}, sk)
    assert envelope.open_signed(code, pub_other) is None

def test_open_signed_rejects_tamper():
    sk = SigningKey.generate()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    code = _make_signed({"typ": "license", "tier": "trial"}, sk)
    bad = base64.urlsafe_b64encode(
        base64.urlsafe_b64decode(code).replace(b"trial", b"s#bsc")).decode()
    assert envelope.open_signed(bad, pub) is None

def test_open_signed_malformed_returns_none():
    assert envelope.open_signed("!!!not-base64!!!", "x") is None
