import io
import json

from glowfish_ocr import JsonLineOcrWorker
from glowfish_ocr.resident import SENTINEL


class SuccessfulProcess:
    pid = 88

    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            SENTINEL + '{"event":"ready","ok":true}\n'
            + SENTINEL + '{"event":"result","ok":true,"job_id":"unicode"}\n'
        )
        self.stderr = io.StringIO("")
        self.returncode = None

    def poll(self):
        return self.returncode


def test_worker_request_escapes_unicode_paths_for_frozen_windows_pipes(tmp_path):
    process = SuccessfulProcess()
    worker = JsonLineOcrWorker(
        ["reader.exe", "--ocr", "ppocrv6_onnx"],
        spawn=lambda _argv, **_kwargs: process,
        terminate=lambda _process: None,
    )
    worker.start()

    image_dir = tmp_path / "\u4e2d\u6587 images"
    output = tmp_path / "\u8bc6\u522b result.json"
    worker.submit(image_dir, output, job_id="unicode")

    raw = process.stdin.getvalue().strip()
    payload = json.loads(raw)
    assert "\\u4e2d\\u6587" in raw
    assert payload["images"] == str(image_dir)
    assert payload["out"] == str(output)
