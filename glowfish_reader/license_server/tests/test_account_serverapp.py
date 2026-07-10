import base64
import os
import socket
import threading
import time

import pytest
import requests
from nacl.signing import SigningKey


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def srv(tmp_path, monkeypatch):
    srv_sk = SigningKey.generate()
    monkeypatch.setenv("LICENSE_DB", str(tmp_path / "account.db"))
    monkeypatch.setenv("SERVER_PRIV", base64.b64encode(bytes(srv_sk)).decode())
    import importlib
    import serverapp
    importlib.reload(serverapp)
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(serverapp.app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        try:
            requests.get(f"http://127.0.0.1:{port}/health", timeout=0.3)
            break
        except Exception:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def test_account_http_lifecycle(srv):
    r = requests.post(srv + "/account/register", json={
        "username": "alice", "password": "secret1", "fingerprint": "fpA"}).json()
    assert r["ok"] and r["account"]["status"] == "trial"

    login = requests.post(srv + "/account/login", json={
        "username": "alice", "password": "secret1", "fingerprint": "fpB"}).json()
    assert login["ok"]

    import sign
    payload = sign.verify_cred(login["cred"], os.environ["SERVER_PRIV"] and sign.pub_from_priv(os.environ["SERVER_PRIV"]), "account")
    check = requests.post(srv + "/account/check", json={"session_id": payload["session_id"]}).json()
    assert check["ok"] and check["account"]["username"] == "alice"

    usage = requests.post(srv + "/account/usage", json={
        "session_id": payload["session_id"],
        "counts": {"ocr_count": 1, "export_count": 1},
    }).json()
    assert usage["ok"]
