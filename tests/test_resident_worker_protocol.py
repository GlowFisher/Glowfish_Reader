import io
import json

from glowfish_ocr import JsonLineOcrWorker
from glowfish_ocr.resident import SENTINEL


class FakeProcess:
    pid = 42

    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            SENTINEL + '{"event":"ready","ok":true}\n'
            + SENTINEL + '{"event":"result","ok":true,"job_id":"job-42"}\n'
        )
        self.stderr = io.StringIO("")
        self.returncode = None

    def poll(self):
        return self.returncode


def test_json_line_worker_roundtrips_job_and_uses_process_hooks(tmp_path):
    process = FakeProcess()
    spawned = {}
    terminated = []

    def spawn(argv, **kwargs):
        spawned.update(argv=argv, kwargs=kwargs)
        return process

    worker = JsonLineOcrWorker(
        ["reader.exe", "--ocr", "ppocrv6_onnx_high"],
        config={"profile": "high_accuracy"},
        spawn=spawn,
        terminate=lambda actual: terminated.append(actual),
    )

    worker.start()
    worker.submit(
        tmp_path / "images",
        tmp_path / "recog.json",
        tmp_path / "progress.json",
        {"profile": "high_accuracy"},
        job_id="job-42",
    )

    payload = json.loads(process.stdin.getvalue().strip())
    assert spawned["argv"][-2:] == ["--worker-config", '{"profile": "high_accuracy"}']
    assert spawned["kwargs"]["purpose"] == "worker"
    assert payload["job_id"] == "job-42"
    assert payload["images"].endswith("images")

    worker.close()
    assert terminated == [process]
