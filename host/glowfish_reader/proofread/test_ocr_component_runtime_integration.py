import json
from pathlib import Path
from types import SimpleNamespace

import ocr_component_runtime


class FakeWorker:
    def __init__(self, prefix, **kwargs):
        self.prefix = prefix
        self.running = False
        self.closed = 0
        self.submissions = []

    def start(self):
        self.running = True
        return self

    def alive(self):
        return self.running

    def submit(self, images, out, progress=None, config=None, job_id=None):
        self.submissions.append((images, out, progress, config, job_id))
        Path(out).write_text(json.dumps({"p001": {"lines": []}}), encoding="utf-8")

    def close(self):
        self.running = False
        self.closed += 1


def test_host_runner_reuses_public_resident_service(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "components" / "ocr" / "src"))
    from glowfish_ocr import ResidentOcrService

    workers = []

    def worker_factory(prefix, **kwargs):
        worker = FakeWorker(prefix, **kwargs)
        workers.append(worker)
        return worker

    service = ResidentOcrService(
        tmp_path,
        worker_factory=worker_factory,
        idle_ttl_seconds=0,
    )
    runner = ocr_component_runtime.ComponentOcrEngineRunner(
        service_factory=lambda job: service,
    )

    for name in ("one.json", "two.json"):
        assert runner(
            ctx=SimpleNamespace(progress_path=tmp_path / "progress.json"),
            image_dir=tmp_path,
            recog_path=tmp_path / name,
            engine="ppocrv6_onnx_high",
        )

    assert len(workers) == 1
    assert len(workers[0].submissions) == 2
    assert (tmp_path / "one.json").exists()
    assert (tmp_path / "two.json").exists()

    runner.shutdown()
    assert workers[0].closed == 1
