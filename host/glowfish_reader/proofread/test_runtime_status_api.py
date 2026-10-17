from fastapi import FastAPI
from fastapi.testclient import TestClient

import runtime_status_api


def test_runtime_status_uses_configured_read_only_provider():
    previous = runtime_status_api.configure_runtime_status_provider(
        lambda: {"ocr": {"mode": "component", "attempts": 3}}
    )
    app = FastAPI()
    app.include_router(runtime_status_api.router)
    try:
        response = TestClient(app).get("/api/runtime/status")
        assert response.status_code == 200
        assert response.json() == {"ocr": {"mode": "component", "attempts": 3}}
    finally:
        runtime_status_api.configure_runtime_status_provider(previous)
