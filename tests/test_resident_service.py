import json
from pathlib import Path

import pytest

from glowfish_ocr import OcrRequest, ResidentOcrService


class FakeWorker:
    def __init__(self, prefix, *, config, start_error=None, **kwargs):
        self.prefix = prefix
        self.config = config
        self.start_error = start_error
        self.started = 0
        self.closed = 0
        self.submissions = []
        self.running = False

    def start(self):
        self.started += 1
        if self.start_error:
            raise self.start_error
        self.running = True
        return self

    def alive(self):
        return self.running

    def submit(self, images, out, progress=None, config=None, job_id=None):
        self.submissions.append((images, out, progress, config, job_id))
        Path(out).write_text(json.dumps({"p001": {"lines": []}}), encoding="utf-8")

    def close(self):
        self.closed += 1
        self.running = False


class FakeTimer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.started = False
        self.cancelled = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def _request(tmp_path, name="one.json", config=None, job_id=None):
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    return OcrRequest(
        images,
        tmp_path / name,
        config=config or {},
        job_id=job_id,
    )


def test_resident_service_reuses_matching_worker_and_forwards_job_id(tmp_path):
    workers = []

    def factory(prefix, **kwargs):
        worker = FakeWorker(prefix, **kwargs)
        workers.append(worker)
        return worker

    service = ResidentOcrService(tmp_path, worker_factory=factory, idle_ttl_seconds=0)
    service.recognize_exact(_request(tmp_path, "one.json", job_id="job-1"))
    service.recognize_exact(_request(tmp_path, "two.json", job_id="job-2"))

    assert len(workers) == 1
    assert [call[-1] for call in workers[0].submissions] == ["job-1", "job-2"]


def test_resident_service_restarts_when_config_changes(tmp_path):
    workers = []

    def factory(prefix, **kwargs):
        worker = FakeWorker(prefix, **kwargs)
        workers.append(worker)
        return worker

    service = ResidentOcrService(tmp_path, worker_factory=factory, idle_ttl_seconds=0)
    service.recognize_exact(_request(tmp_path, "one.json", {"text_det_box_thresh": 0.4}))
    service.recognize_exact(_request(tmp_path, "two.json", {"text_det_box_thresh": 0.5}))

    assert len(workers) == 2
    assert workers[0].closed == 1


def test_resident_service_retries_then_opens_startup_circuit(tmp_path):
    workers = []

    def factory(prefix, **kwargs):
        worker = FakeWorker(prefix, start_error=RuntimeError("boom"), **kwargs)
        workers.append(worker)
        return worker

    service = ResidentOcrService(
        tmp_path,
        worker_factory=factory,
        idle_ttl_seconds=0,
        startup_attempts=2,
    )

    with pytest.raises(RuntimeError, match="failed to start"):
        service.recognize_exact(_request(tmp_path))
    assert len(workers) == 2
    assert not service.prewarm("ppocrv6_onnx_high").ok
    assert len(workers) == 2


def test_resident_service_idle_timer_and_shutdown_close_worker(tmp_path):
    workers = []
    timers = []

    def factory(prefix, **kwargs):
        worker = FakeWorker(prefix, **kwargs)
        workers.append(worker)
        return worker

    def timer_factory(interval, callback):
        timer = FakeTimer(interval, callback)
        timers.append(timer)
        return timer

    service = ResidentOcrService(
        tmp_path,
        worker_factory=factory,
        timer_factory=timer_factory,
        idle_ttl_seconds=12,
    )
    service.recognize_exact(_request(tmp_path))
    assert timers[0].started
    assert timers[0].interval == 12

    timers[0].callback()
    assert workers[0].closed == 1

    service.recognize_exact(_request(tmp_path, "two.json"))
    service.shutdown()
    assert workers[1].closed == 1
    assert timers[1].cancelled
