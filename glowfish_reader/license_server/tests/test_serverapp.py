import os, time, base64, socket, threading
import requests, pytest
from nacl.signing import SigningKey

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

def test_rate_limit_returns_429(tmp_path, monkeypatch):
    srv_sk = SigningKey.generate()
    monkeypatch.setenv("LICENSE_DB", str(tmp_path / "rl.db"))
    monkeypatch.setenv("SERVER_PRIV", base64.b64encode(bytes(srv_sk)).decode())
    monkeypatch.setenv("LICENSE_RATE_LIMIT", "3")          # 小阈值便于触发
    import importlib, serverapp; importlib.reload(serverapp)
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(serverapp.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try: requests.get(f"http://127.0.0.1:{port}/health", timeout=0.3); break
        except Exception: time.sleep(0.1)
    base = f"http://127.0.0.1:{port}"
    try:
        codes = [requests.post(base + "/account/logout", json={"session_id": "no-such"}).status_code
                 for _ in range(4)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
    finally:
        server.should_exit = True
