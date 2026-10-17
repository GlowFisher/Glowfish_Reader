import json
from types import SimpleNamespace

import pytest

import content_api


@pytest.fixture(autouse=True)
def reset_ocr_engine_runner():
    previous = content_api.configure_ocr_engine_runner(None)
    try:
        yield
    finally:
        content_api.configure_ocr_engine_runner(previous)


def _ctx(tmp_path):
    return SimpleNamespace(progress_path=tmp_path / "progress.json")


def test_configured_runner_handles_single_engine_attempt(tmp_path, monkeypatch):
    calls = []
    output = tmp_path / "recog.json"

    def runner(**kwargs):
        calls.append(kwargs)
        output.write_text(json.dumps({"page-1": {"lines": []}}), encoding="utf-8")

    def unexpected_legacy(*args, **kwargs):
        raise AssertionError("legacy runtime should not run")

    monkeypatch.setattr(content_api, "_run_engine_legacy", unexpected_legacy)
    content_api.configure_ocr_engine_runner(runner)

    content_api._run_engine(_ctx(tmp_path), tmp_path, output, "ppocrv6_onnx_high")

    assert output.exists()
    assert calls[0]["engine"] == "ppocrv6_onnx_high"
    assert calls[0]["recog_path"] == output


def test_runner_exception_falls_back_to_legacy(tmp_path, monkeypatch):
    output = tmp_path / "recog.json"
    legacy_calls = []

    def failing_runner(**kwargs):
        raise RuntimeError("component unavailable")

    def one_shot(ctx, image_dir, recog_path, engine, job=None):
        legacy_calls.append((ctx, image_dir, recog_path, engine, job))
        recog_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine_one_shot", one_shot)
    content_api.configure_ocr_engine_runner(failing_runner)

    content_api._run_engine(_ctx(tmp_path), tmp_path, output, "ppocrv6_onnx_high")

    assert len(legacy_calls) == 1
    assert legacy_calls[0][3] == "ppocrv6_onnx_high"


def test_runner_can_decline_without_leaking_partial_output(tmp_path, monkeypatch):
    output = tmp_path / "recog.json"
    legacy_saw_clean_path = []

    def declining_runner(**kwargs):
        output.write_text('{"partial": true}', encoding="utf-8")
        return False

    def one_shot(ctx, image_dir, recog_path, engine, job=None):
        legacy_saw_clean_path.append(not recog_path.exists())
        recog_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine_one_shot", one_shot)
    content_api.configure_ocr_engine_runner(declining_runner)

    content_api._run_engine(_ctx(tmp_path), tmp_path, output, "ppocrv6_onnx_high")

    assert legacy_saw_clean_path == [True]


def test_runner_without_output_is_treated_as_failure(tmp_path, monkeypatch):
    output = tmp_path / "recog.json"
    legacy_calls = []

    monkeypatch.setattr(content_api, "_run_engine_one_shot", lambda *args, **kwargs: legacy_calls.append(True))
    content_api.configure_ocr_engine_runner(lambda **kwargs: None)

    content_api._run_engine(_ctx(tmp_path), tmp_path, output, "ppocrv6_onnx_high")

    assert legacy_calls == [True]


def test_prewarm_prefers_configured_runner(monkeypatch):
    calls = []

    class Runner:
        def __call__(self, **kwargs):
            return True

        def prewarm(self, engine):
            calls.append(engine)
            return True

    def unexpected_legacy(*args, **kwargs):
        raise AssertionError("legacy prewarm should not run")

    monkeypatch.setattr(content_api, "_worker_for", unexpected_legacy)
    content_api.configure_ocr_engine_runner(Runner())

    assert content_api.prewarm("ppocrv6_onnx_high")
    assert calls == ["ppocrv6_onnx_high"]
