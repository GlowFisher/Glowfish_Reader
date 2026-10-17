import json
from pathlib import Path

from glowfish_ocr import OcrRequest, ResidentOcrService


class Worker:
    def __init__(self, prefix, *, config, **_kwargs):
        self.prefix, self.config, self.running = prefix, config, False

    def start(self):
        self.running = True
        return self

    def alive(self):
        return self.running

    def submit(self, _images, output, *_args, **_kwargs):
        Path(output).write_text(json.dumps({"p001": {"lines": []}}), encoding="utf-8")

    def close(self):
        self.running = False


def test_resident_service_launches_verified_gpu_worker_with_existing_protocol(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "page.png").write_bytes(b"fixture")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    worker_exe = runtime / "glowfish_gpu_worker.exe"
    worker_exe.write_bytes(b"fixture")
    captured = []

    def factory(prefix, **kwargs):
        instance = Worker(prefix, **kwargs)
        captured.append(instance)
        return instance

    service = ResidentOcrService(tmp_path, worker_factory=factory, idle_ttl_seconds=0)
    service.recognize_exact(OcrRequest(
        images, tmp_path / "recog.json", config={
            "provider": "cuda", "gpu_runtime_dir": str(runtime), "gpu_runtime_version": "1.0.0",
        },
    ))

    assert captured[0].prefix == [str(worker_exe)]
    assert captured[0].config["provider"] == "cuda"
