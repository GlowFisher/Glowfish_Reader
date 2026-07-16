import subprocess
from types import SimpleNamespace

import pytest

import ocr_component_runtime


def test_component_runtime_is_explicitly_opt_in(monkeypatch):
    monkeypatch.delenv("GLOWFISH_OCR_COMPONENT_RUNTIME", raising=False)
    assert not ocr_component_runtime.component_runtime_enabled()
    assert ocr_component_runtime.component_runtime_enabled("YES")
    assert not ocr_component_runtime.component_runtime_enabled("0")


def test_component_runner_translates_one_host_attempt(tmp_path):
    captured = {}
    cancel_checks = []

    def check_cancelled():
        cancel_checks.append(True)

    job = SimpleNamespace(
        job_id="job-1",
        progress_path=tmp_path / "job-progress.json",
        check_cancelled=check_cancelled,
    )

    class Service:
        def recognize_exact(self, request):
            captured["request"] = request
            request.output_path.write_text("{}", encoding="utf-8")

    def request_factory(**kwargs):
        return SimpleNamespace(**kwargs)

    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=lambda actual_job: Service(),
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
    assert captured["request"].engine == "ppocrv6_onnx_high"
    assert captured["request"].progress_path == job.progress_path
    assert output.exists()
    assert cancel_checks == [True, True]


def test_tracked_runner_preserves_process_metadata_and_check(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 7, "out", "err")

    monkeypatch.setattr(ocr_component_runtime.windows_process, "run", fake_run)
    runner = ocr_component_runtime._tracked_process_runner(SimpleNamespace(job_id="job-7"))

    with pytest.raises(subprocess.CalledProcessError) as error:
        runner(["reader.exe", "--ocr"], check=True, timeout=12, cwd="runtime")

    assert error.value.returncode == 7
    assert captured["kwargs"]["purpose"] == "component-ocr"
    assert captured["kwargs"]["job_id"] == "job-7"
    assert captured["kwargs"]["timeout"] == 12
