# -*- coding: utf-8 -*-
import os

import desktop_app


def test_start_server_does_not_force_onnx(monkeypatch):
    calls = {}

    monkeypatch.delenv("SHUPAI_ENGINE", raising=False)
    monkeypatch.setattr(desktop_app, "_free_port", lambda: 9999)

    class FakeServer:
        def __init__(self, config):
            calls["config"] = config

        def run(self):
            pass

    class FakeUvicorn:
        class Config:
            def __init__(self, app, host, port, log_level):
                self.app = app
                self.host = host
                self.port = port
                self.log_level = log_level

        Server = FakeServer

    class FakeThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon

        def start(self):
            calls["thread_started"] = True

    monkeypatch.setitem(os.environ, "SHUPAI_OPEN_BROWSER", "1")
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn)
    monkeypatch.setitem(__import__("sys").modules, "server", type("S", (), {"app": object()}))
    monkeypatch.setattr("threading.Thread", FakeThread)

    server, host, port = desktop_app._start_server()

    assert server is not None
    assert host == "127.0.0.1"
    assert port == 9999
    assert "SHUPAI_ENGINE" not in os.environ
    assert os.environ["SHUPAI_MODE"] == "single"
    assert os.environ["SHUPAI_OPEN_BROWSER"] == "0"
