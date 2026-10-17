import io
import json
import threading

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
        checkpoint_dir=tmp_path / "checkpoint",
        attempt=3,
    )

    payload = json.loads(process.stdin.getvalue().strip())
    assert spawned["argv"][-2:] == ["--worker-config", '{"profile": "high_accuracy"}']
    assert spawned["kwargs"]["purpose"] == "worker"
    assert payload["job_id"] == "job-42"
    assert payload["images"].endswith("images")
    assert payload["checkpoint_dir"].endswith("checkpoint")
    assert payload["attempt"] == 3

    worker.close()
    assert terminated == [process]


def test_worker_timeout_is_refreshed_by_progress_activity(tmp_path):
    process = FakeProcess()
    process.stdout = io.StringIO(SENTINEL + '{"event":"ready","ok":true}\n')
    worker = JsonLineOcrWorker(
        ["reader.exe", "--ocr", "ppocrv6_onnx_high"],
        spawn=lambda _argv, **_kwargs: process,
        terminate=lambda _process: None,
        result_timeout=0.08,
    )
    progress = tmp_path / "progress.json"
    progress.write_text('{"done":0}', encoding="utf-8")
    worker.start()

    refresh = threading.Timer(
        0.03, lambda: progress.write_text('{"done":1}', encoding="utf-8")
    )
    result = threading.Timer(
        0.11,
        lambda: worker._events.put(
            {"event": "result", "ok": True, "job_id": "slow-job"}
        ),
    )
    refresh.start()
    result.start()

    event = worker.submit(
        tmp_path / "images",
        tmp_path / "recog.json",
        progress,
        job_id="slow-job",
    )

    assert event["ok"]
    worker.close()
