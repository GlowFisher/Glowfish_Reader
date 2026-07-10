from licensing import store

def test_load_missing_returns_empty_defaults(tmp_path):
    d = store.load(str(tmp_path / "license.json"))
    assert d["account_cred"] is None and d["max_seen_ts"] == 0

def test_save_load_roundtrip(tmp_path):
    p = str(tmp_path / "license.json")
    store.save(p, {"account_cred": "abc", "account_session_id": "S5"})
    d = store.load(p)
    assert d["account_cred"] == "abc" and d["account_session_id"] == "S5"

def test_bump_seen_is_monotonic(tmp_path):
    p = str(tmp_path / "license.json")
    assert store.bump_seen(p, 100) == 100
    assert store.bump_seen(p, 50) == 100      # 不回退
    assert store.bump_seen(p, 200) == 200
