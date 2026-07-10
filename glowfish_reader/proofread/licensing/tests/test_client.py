import os, sys, time, base64, socket, threading
from pathlib import Path
import pytest, requests
from nacl.signing import SigningKey
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "license_server"))

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

@pytest.fixture
def srv(tmp_path, monkeypatch):
    srv_sk = SigningKey.generate()
    os.environ["LICENSE_DB"] = str(tmp_path / "t.db")
    os.environ["SERVER_PRIV"] = base64.b64encode(bytes(srv_sk)).decode()
    import importlib, serverapp; importlib.reload(serverapp)
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(serverapp.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try: requests.get(f"http://127.0.0.1:{port}/health", timeout=0.3); break
        except Exception: time.sleep(0.1)
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", f"http://127.0.0.1:{port}")
    yield
    server.should_exit = True

def test_account_check_passes_through_business_json(srv):
    """真实服务器的业务失败（带 ok 字段）须原样透传，不被降级成 unavailable。"""
    from licensing import client
    r = client.account_check("bogus-session", "fpA", count_login=True)
    assert r["ok"] is False and r["reason"] == "not_logged_in"

def test_network_failure_is_soft(monkeypatch):
    monkeypatch.setenv("SHUPAI_LICENSE_SERVER", "http://127.0.0.1:1")   # 必失败端口
    from licensing import client
    r = client.account_check("s", "fpA")
    assert r["ok"] is False and r["reason"] == "network"

def test_missing_endpoint_maps_to_unavailable(srv):
    """已退役端点（如激活码 /activate）的 404 detail 响应须判 unavailable，绝不冒充业务失败。"""
    from licensing import client
    r = client._post("/activate", {"token": "t", "fingerprint": "fpA"})
    assert r["ok"] is False and r["reason"] == "unavailable"
