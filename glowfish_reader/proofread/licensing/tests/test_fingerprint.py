from licensing import fingerprint as fp

def test_stable_same_parts():
    a = fp.fingerprint_from_parts(["guid-x", "host-y"])
    b = fp.fingerprint_from_parts(["guid-x", "host-y"])
    assert a == b and len(a) == 64

def test_sensitive_to_change():
    assert fp.fingerprint_from_parts(["guid-x"]) != fp.fingerprint_from_parts(["guid-z"])

def test_ignores_empty_and_order_normalized():
    # 空串过滤，避免缺一项就换指纹；非空部件顺序固定
    assert fp.fingerprint_from_parts(["a", "", "b"]) == fp.fingerprint_from_parts(["a", "b"])

def test_machine_fingerprint_is_hex64():
    v = fp.machine_fingerprint()
    assert isinstance(v, str) and len(v) == 64
    int(v, 16)  # 是合法十六进制
