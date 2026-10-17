import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import appconfig
import content_api
import ocr_component_runtime


@pytest.fixture(autouse=True)
def reset_runner():
    previous = content_api.configure_ocr_engine_runner(None)
    try:
        yield
    finally:
        content_api.configure_ocr_engine_runner(previous)
        sys.modules.pop("server_v2", None)


def test_runtime_policy_supports_named_canary_and_rollback_values(monkeypatch):
    monkeypatch.delenv("GLOWFISH_OCR_COMPONENT_RUNTIME", raising=False)
    assert ocr_component_runtime.component_runtime_mode() == "component"
    assert ocr_component_runtime.component_runtime_mode("component") == "component"
    assert ocr_component_runtime.component_runtime_mode("1") == "component"
    assert ocr_component_runtime.component_runtime_mode("legacy") == "legacy"
    assert ocr_component_runtime.component_runtime_mode("0") == "legacy"


def test_runner_records_component_attempt_prewarm_and_fallback(tmp_path):
    class Service:
        def recognize_exact(self, request):
            request.output_path.write_text("{}", encoding="utf-8")

        def prewarm(self, engine):
            return SimpleNamespace(ok=True)

    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=lambda job: Service(),
        request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    assert runner(
        ctx=SimpleNamespace(progress_path=tmp_path / "progress.json"),
        image_dir=tmp_path,
        recog_path=tmp_path / "recog.json",
        engine="ppocrv6_onnx_high",
    )
    assert runner.prewarm("ppocrv6_onnx_high")
    runner.record_fallback(
        engine="ppocrv6_onnx_high",
        success=True,
        error=RuntimeError("component unavailable"),
    )

    status = runner.status()
    assert status["metrics"]["component_attempts"] == 1
    assert status["metrics"]["component_successes"] == 1
    assert status["metrics"]["component_success_rate"] == 1.0
    assert status["metrics"]["prewarm_successes"] == 1
    assert status["metrics"]["fallback_successes"] == 1
    assert status["metrics"]["last_error_type"] == "RuntimeError"


def test_runner_records_component_failure(tmp_path):
    class Service:
        def recognize_exact(self, request):
            raise ValueError("component unavailable")

    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=lambda job: Service(),
        request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    with pytest.raises(ValueError):
        runner(
            ctx=SimpleNamespace(progress_path=tmp_path / "progress.json"),
            image_dir=tmp_path,
            recog_path=tmp_path / "recog.json",
            engine="ppocrv6_onnx_high",
        )

    metrics = runner.status()["metrics"]
    assert metrics["component_attempts"] == 1
    assert metrics["component_failures"] == 1
    assert metrics["component_success_rate"] == 0.0
    assert metrics["last_error_type"] == "ValueError"


def test_content_runner_reports_legacy_fallback_success_and_failure(tmp_path, monkeypatch):
    class Runner:
        def __init__(self):
            self.events = []

        def __call__(self, **kwargs):
            raise RuntimeError("component unavailable")

        def record_fallback(self, **event):
            self.events.append(event)

    runner = Runner()
    content_api.configure_ocr_engine_runner(runner)
    ctx = SimpleNamespace(progress_path=tmp_path / "progress.json")
    output = tmp_path / "recog.json"

    def successful_legacy(ctx, image_dir, recog_path, engine, job=None):
        recog_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine_one_shot", successful_legacy)
    content_api._run_engine(ctx, tmp_path, output, "ppocrv6_onnx_high")
    assert runner.events[-1]["success"] is True
    assert isinstance(runner.events[-1]["error"], RuntimeError)

    def failed_legacy(ctx, image_dir, recog_path, engine, job=None):
        raise ValueError("legacy unavailable")

    output.unlink()
    monkeypatch.setattr(content_api, "_run_engine_one_shot", failed_legacy)
    with pytest.raises(ValueError):
        content_api._run_engine(ctx, tmp_path, output, "ppocrv6_onnx_high")
    assert runner.events[-1]["success"] is False
    assert isinstance(runner.events[-1]["error"], ValueError)


def test_server_status_exposes_component_metrics_and_rollback(tmp_path, monkeypatch):
    class FakeRunner:
        def __call__(self, **kwargs):
            return True

        def status(self):
            return {
                "metrics": {"component_attempts": 2},
                "worker": {"created": True, "alive": True, "pid": 123},
            }

        def shutdown(self):
            pass

    runner = FakeRunner()
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "src"))
    monkeypatch.syspath_prepend(str(root / "components" / "ocr" / "src"))
    monkeypatch.setattr(appconfig, "data_root", lambda: tmp_path)
    monkeypatch.setenv("GLOWFISH_OCR_COMPONENT_RUNTIME", "component")
    monkeypatch.setattr(ocr_component_runtime, "ComponentOcrEngineRunner", lambda **_kwargs: runner)

    runtime = importlib.import_module("server_v2")
    status = runtime._runtime_status()["ocr"]
    assert runtime.OCR_POLICY == "component"
    assert status["mode"] == "component"
    assert status["metrics"]["component_attempts"] == 2
    assert status["worker"]["alive"] is True
    assert "GLOWFISH_OCR_COMPONENT_RUNTIME=legacy" in status["rollback"]
