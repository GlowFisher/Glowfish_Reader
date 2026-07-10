import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _client(monkeypatch, mode, expires_at):
    monkeypatch.setenv("SHUPAI_ACCOUNT_MODE", mode)
    monkeypatch.setenv("SHUPAI_ACCOUNT_EXPIRES_AT", expires_at)

    import appconfig
    import auth_api
    import userctx
    import server

    importlib.reload(appconfig)
    importlib.reload(auth_api)
    importlib.reload(userctx)
    importlib.reload(server)

    def fake_current_user():
        return {"id": 1, "username": "zhangsan", "display": "张三"}

    server.app.dependency_overrides[userctx.current_user] = fake_current_user
    return TestClient(server.app)


def test_me_includes_trial_entitlement(monkeypatch):
    client = _client(monkeypatch, "trial", "2026-08-31")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["entitlement"] == {"mode": "trial", "expires_at": "2026-08-31"}


def test_me_includes_member_entitlement(monkeypatch):
    client = _client(monkeypatch, "member", "2026-08-31")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["entitlement"] == {"mode": "member", "expires_at": "2026-08-31"}

