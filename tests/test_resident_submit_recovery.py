import json
from pathlib import Path

from glowfish_ocr import OcrRequest, ResidentOcrService


class Worker:
    def __init__(self, prefix, *, fail_submit=False, **kwargs):
        self.fail_submit = fail_submit
        self.closed = 0
        self.running = False

    def start(self):
        self.running = True
        return self

    def alive(self):
        return self.running

    def submit(self, images, out, progress=None, config=None, job_id=None):
        if self.fail_submit:
            raise RuntimeError("worker pipe broke")
        Path(out).write_text(json.dumps({"p001": {"lines": []}}), encoding="utf-8")

    def close(self):
        self.closed += 1
        self.running = False


def test_submit_failure_closes_worker_and_rebuilds_once(tmp_path):
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "page.png").write_bytes(b"fixture")
    workers = []

    def factory(prefix, **kwargs):
        worker = Worker(prefix, fail_submit=not workers)
        workers.append(worker)
        return worker

    service = ResidentOcrService(tmp_path, worker_factory=factory, idle_ttl_seconds=0)
    result = service.recognize_exact(OcrRequest(image_dir, tmp_path / "recog.json"))

    assert result.output_path.is_file()
    assert len(workers) == 2
    assert service._submit_rebuilds == 1
    assert workers[0].closed == 1
    assert workers[1].closed == 0
