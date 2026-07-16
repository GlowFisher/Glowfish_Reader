from pathlib import Path
from types import SimpleNamespace

import ocr_component_runtime


def test_component_runtime_is_explicitly_opt_in(monkeypatch):
    monkeypatch.delenv("GLOWFISH_OCR_COMPONENT_RUNTIME", raising=False)
    assert not ocr_component_runtime.component_runtime_enabled()
    assert ocr_component_runtime.component_runtime_enabled("YES")
    assert not ocr_component_runtime.component_runtime_enabled("0")


def test_component_runner_reuses_service_and_forwards_job_metadata(tmp_path):
    captured = {}
    cancel_checks = []
    factory_calls = []

    def check_cancelled():
        cancel_checks.append(True)

    job = SimpleNamespace(
        job_id="job-1",
        progress_path=tmp_path / "job-progress.json",
        check_cancelled=check_cancelled,
    )

    class Service:
        def __init__(self):
            self.shutdown_calls = 0

        def recognize_exact(self, request):
            captured["request"] = request
            request.output_path.write_text("{}", encoding="utf-8")

        def prewarm(self, engine):
            captured["prewarm"] = engine
            return SimpleNamespace(ok=True)

        def shutdown(self):
            self.shutdown_calls += 1

    def request_factory(**kwargs):
        return SimpleNamespace(**kwargs)

    service = Service()

    def service_factory(actual_job):
        factory_calls.append(actual_job)
        return service

    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=service_factory,
        request_factory=request_factory,
    )
    output = tmp_path / "recog.json"

    assert runner(
        ctx=SimpleNamespace(progress_path=tmp_path / "ctx-progress.json"),
        image_dir=tmp_path,
        recog_path=output,
        engine="ppocrv6_onnx_high",
        job=job,
    )
    assert runner.prewarm("ppocrv6_onnx_high")
    assert captured["request"].engine == "ppocrv6_onnx_high"
    assert captured["request"].progress_path == job.progress_path
    assert captured["request"].job_id == "job-1"
    assert captured["prewarm"] == "ppocrv6_onnx_high"
    assert output.exists()
    assert cancel_checks == [True, True]
    assert factory_calls == [job]

    runner.shutdown()
    assert service.shutdown_calls == 1


def test_default_worker_factory_uses_host_process_lifecycle(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "components" / "ocr" / "src"))
    import glowfish_ocr

    captured = {}

    def fake_worker(prefix, **kwargs):
        captured.update(prefix=prefix, kwargs=kwargs)
        return "worker"

    monkeypatch.setattr(glowfish_ocr, "JsonLineOcrWorker", fake_worker)
    worker = ocr_component_runtime._default_worker_factory(
        ["reader.exe", "--ocr", "ppocrv6_onnx_high"],
        env={"TEST": "1"},
        model_type="ppocrv6_onnx_high",
        config={"profile": "high_accuracy"},
    )

    assert worker == "worker"
    assert captured["kwargs"]["spawn"] is ocr_component_runtime.windows_process.spawn
    assert captured["kwargs"]["terminate"] is ocr_component_runtime.windows_process.terminate_process
