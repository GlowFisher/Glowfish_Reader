import gpu_acceleration_api as api


def test_cpu_preference_blocks_an_already_active_gpu_runtime(monkeypatch):
    monkeypatch.setattr(api, "_preference", lambda _ctx: "cpu")
    monkeypatch.setattr(api, "_status", lambda _ctx: {"state": "active", "runtime_version": "1.0.0"})

    assert api.execution_config(object(), "ppocrv6_onnx_high") == {"provider": "cpu"}


def test_disable_keeps_runtime_but_saves_cpu_preference(monkeypatch):
    saved = {}
    monkeypatch.setattr(api, "load_settings", lambda _ctx: {"ocr_acceleration": "auto"})
    monkeypatch.setattr(api, "save_settings", lambda _ctx, value: saved.update(value))
    monkeypatch.setattr(api, "_status", lambda _ctx: {"preference": "cpu", "state": "active"})

    result = api.disable_acceleration(object())

    assert saved["ocr_acceleration"] == "cpu"
    assert result["preference"] == "cpu"
