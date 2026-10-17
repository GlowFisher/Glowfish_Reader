# -*- coding: utf-8 -*-
import json
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import ocr_atomic
import ocr_job_manager
import windows_process


def test_ten_duplicate_requests_execute_once(tmp_path):
    manager = ocr_job_manager.OcrJobManager()
    calls = 0
    lock = threading.Lock()

    def runner(job):
        nonlocal calls
        with lock:
            calls += 1
        time.sleep(0.08)
        return job.job_id

    def invoke(index):
        return manager.run("local", tmp_path / "_recog.json", "engine", "hash", str(index), runner)

    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(invoke, range(10)))
        assert calls == 1
        assert len(set(results)) == 1
    finally:
        manager.shutdown(wait=True)


def test_different_configs_for_same_output_are_serialized(tmp_path):
    manager = ocr_job_manager.OcrJobManager()
    active = 0
    peak = 0
    lock = threading.Lock()

    def runner(job):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return job.config_hash

    output = tmp_path / "_recog.json"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(manager.run, "local", output, "a", "one", "r1", runner),
                pool.submit(manager.run, "local", output, "b", "two", "r2", runner),
            ]
            assert {future.result() for future in futures} == {"one", "two"}
        assert peak == 1
    finally:
        manager.shutdown(wait=True)


def test_atomic_failure_preserves_previous_result(tmp_path):
    manager = ocr_job_manager.OcrJobManager()
    output = tmp_path / "_recog.json"
    output.write_text('{"old": true}', encoding="utf-8")
    ctx = SimpleNamespace(uid="local")

    def failing(_ctx, _images, staged, _engine, job=None):
        staged.write_text("not-json", encoding="utf-8")
        raise RuntimeError("boom")

    try:
        with pytest.raises(RuntimeError, match="boom"):
            ocr_atomic.run_atomic(
                manager, ctx=ctx, image_dir=tmp_path, output_path=output,
                engine="engine", config_hash="hash", request_id="request",
                direct_runner=failing, expected_pages=0)
        assert json.loads(output.read_text(encoding="utf-8")) == {"old": True}
    finally:
        manager.shutdown(wait=True)


def test_atomic_commit_replaces_only_after_valid_json(tmp_path):
    manager = ocr_job_manager.OcrJobManager()
    output = tmp_path / "_recog.json"
    output.write_text('{"old": true}', encoding="utf-8")
    ctx = SimpleNamespace(uid="local")

    def successful(_ctx, _images, staged, _engine, job=None):
        staged.write_text('{"p001": {"lines": []}}', encoding="utf-8")
        return "engine"

    try:
        actual = ocr_atomic.run_atomic(
            manager, ctx=ctx, image_dir=tmp_path, output_path=output,
            engine="engine", config_hash="hash", request_id="request",
            direct_runner=successful, expected_pages=1)
        assert actual == "engine"
        assert "p001" in json.loads(output.read_text(encoding="utf-8"))
    finally:
        manager.shutdown(wait=True)


def test_terminate_escalates_to_kill(monkeypatch):
    class FakeProcess:
        pid = 123
        returncode = None

        def __init__(self):
            self.terminated = 0
            self.killed = 0

        def poll(self):
            return None

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired("fake", timeout)

        def terminate(self):
            self.terminated += 1

        def kill(self):
            self.killed += 1

    process = FakeProcess()
    windows_process.terminate_process(process, graceful_timeout=0, terminate_timeout=0)
    assert process.terminated == 1
    assert process.killed == 1


def test_windows_children_are_hidden():
    kwargs = windows_process.hidden_process_kwargs()
    if windows_process.os.name == "nt":
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE
    else:
        assert kwargs == {}
