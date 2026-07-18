from types import SimpleNamespace

import pytest

import content_api
import ocr_component_runtime


@pytest.fixture(autouse=True)
def restore_runner():
    previous = content_api.configure_ocr_engine_runner(None)
    try:
        yield
    finally:
        content_api.configure_ocr_engine_runner(previous)


def _ctx(tmp_path):
    return SimpleNamespace(progress_path=tmp_path / "progress.json")


def test_component_failure_uses_exactly_one_oneshot_and_no_legacy_resident(tmp_path, monkeypatch):
    output = tmp_path / "output.json"
    calls = []

    def runner(**_kwargs):
        raise RuntimeError("resident failed after rebuild")

    def one_shot(ctx, image_dir, recog_path, engine, job=None):
        calls.append((engine, job))
        recog_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(content_api, "_run_engine_one_shot", one_shot)
    monkeypatch.setattr(
        content_api, "_run_engine_legacy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("component fallback must not create a legacy resident worker")
        ),
    )
    content_api.configure_ocr_engine_runner(runner)

    content_api._run_engine(_ctx(tmp_path), tmp_path, output, "ppocrv6_onnx_high")

    assert len(calls) == 1


def test_input_unavailable_never_starts_fallback(tmp_path, monkeypatch):
    class InputUnavailable(ValueError):
        error_type = "ocr_input_unavailable"

    content_api.configure_ocr_engine_runner(
        lambda **_kwargs: (_ for _ in ()).throw(InputUnavailable("no images"))
    )
    monkeypatch.setattr(
        content_api, "_run_engine_one_shot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fallback started")),
    )

    with pytest.raises(InputUnavailable):
        content_api._run_engine(
            _ctx(tmp_path), tmp_path, tmp_path / "output.json", "ppocrv6_onnx_high"
        )


def test_runtime_status_exposes_pid_retry_fallback_and_structured_error(tmp_path):
    class StructuredError(RuntimeError):
        error_type = "ocr_worker_job_failed"

    class Worker:
        pid = 1234

        def alive(self):
            return True

    class Service:
        _worker = Worker()
        _submit_rebuilds = 1

        def recognize_exact(self, _request):
            raise StructuredError("failed")

    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=lambda _job: Service(),
        request_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )
    with pytest.raises(StructuredError):
        runner(
            ctx=_ctx(tmp_path), image_dir=tmp_path,
            recog_path=tmp_path / "output.json", engine="ppocrv6_onnx_high",
        )
    runner.record_fallback(
        engine="ppocrv6_onnx_high", success=False, error=StructuredError("failed")
    )

    status = runner.status()
    assert status["worker"]["pid"] == 1234
    assert status["retry_count"] == 1
    assert status["one_shot_fallback"] is True
    assert status["last_error_type"] == "ocr_worker_job_failed"
