import io

import pytest

from glowfish_ocr import JsonLineOcrWorker, OcrWorkerError
from glowfish_ocr.resident import SENTINEL


class FailedProcess:
    pid = 77

    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(
            SENTINEL + '{"event":"ready","ok":true}\n'
            + SENTINEL
            + '{"event":"result","ok":false,"job_id":"job-77",'
              '"error_type":"ocr_worker_job_failed","stage":"recognition",'
              '"reason":"model invocation failed"}\n'
        )
        self.stderr = io.StringIO("")
        self.returncode = None

    def poll(self):
        return self.returncode


def test_worker_failure_preserves_structured_error_fields(tmp_path):
    process = FailedProcess()
    worker = JsonLineOcrWorker(
        ["reader.exe", "--ocr", "ppocrv6_onnx"],
        spawn=lambda _argv, **_kwargs: process,
        terminate=lambda _process: None,
    )
    worker.start()

    with pytest.raises(OcrWorkerError) as caught:
        worker.submit(
            tmp_path / "images",
            tmp_path / "output.json",
            job_id="job-77",
        )

    assert caught.value.error_type == "ocr_worker_job_failed"
    assert caught.value.stage == "recognition"
    assert caught.value.reason == "model invocation failed"
