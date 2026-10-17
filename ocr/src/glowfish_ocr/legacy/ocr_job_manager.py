# -*- coding: utf-8 -*-
"""Single-flight OCR scheduling, job-scoped progress, and cancellation."""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path


TERMINAL_STATES = {"done", "failed", "cancelled"}


class OcrCancelled(RuntimeError):
    pass


@dataclass
class OcrJob:
    key: tuple
    user_id: str
    output_path: Path
    engine: str
    config_hash: str
    request_id: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    state: str = "queued"
    waiters: int = 1
    worker_pid: int | None = None
    fallback_pid: int | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    error: str | None = None
    _percent: int = 0

    @property
    def directory(self):
        return self.output_path.parent / "_ocr_jobs" / self.job_id

    @property
    def progress_path(self):
        return self.directory / "progress.json"

    @property
    def staged_output(self):
        return self.directory / "recog.tmp.json"

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise OcrCancelled("OCR job cancelled")

    def progress(self, state=None, *, done=None, total=None, percent=None, **extra):
        if state:
            self.state = state
        if percent is None and done is not None and total:
            percent = int(max(0, min(99, (float(done) / float(total)) * 90)))
        if self.state == "done":
            percent = 100
        if percent is not None:
            self._percent = max(self._percent, int(percent))
        payload = {
            "job_id": self.job_id,
            "request_id": self.request_id,
            "phase": self.state,
            "done": done if done is not None else self._percent,
            "total": total if total is not None else 100,
            "percent": self._percent,
            "engine": self.engine,
            "waiters": self.waiters,
        }
        payload.update(extra)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.progress_path)
        return payload

    def status(self):
        try:
            payload = json.loads(self.progress_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {"phase": self.state, "percent": self._percent}
        payload.update({
            "job_id": self.job_id,
            "request_id": self.request_id,
            "engine": self.engine,
            "waiters": self.waiters,
        })
        if self.error:
            payload["error"] = self.error
        return payload


class OcrJobManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="glowfish-ocr")
        self._jobs: dict[tuple, OcrJob] = {}
        self._active_by_user: dict[str, OcrJob] = {}
        self._last_by_user: dict[str, OcrJob] = {}
        self._stopping = False

    @staticmethod
    def key(user_id, output_path, engine, config_hash):
        resolved = str(Path(output_path).resolve()).casefold()
        return str(user_id), resolved, str(engine), str(config_hash)

    def run(self, user_id, output_path, engine, config_hash, request_id, runner):
        key = self.key(user_id, output_path, engine, config_hash)
        with self._lock:
            if self._stopping:
                raise RuntimeError("application_stopping")
            job = self._jobs.get(key)
            if job and job.future and not job.future.done():
                job.waiters += 1
                future = job.future
            else:
                job = OcrJob(
                    key=key, user_id=str(user_id), output_path=Path(output_path).resolve(),
                    engine=str(engine), config_hash=str(config_hash),
                    request_id=str(request_id or uuid.uuid4().hex),
                )
                self._jobs[key] = job
                future = self._executor.submit(self._execute, job, runner)
                job.future = future
        return future.result()

    def _execute(self, job, runner):
        with self._lock:
            self._active_by_user[job.user_id] = job
        job.started_at = time.time()
        job.directory.mkdir(parents=True, exist_ok=True)
        job.progress("starting_worker", percent=1)
        try:
            job.check_cancelled()
            result = runner(job)
            job.check_cancelled()
            job.progress("done", percent=100)
            return result
        except OcrCancelled as exc:
            job.error = str(exc)
            job.progress("cancelled")
            raise
        except Exception as exc:
            job.error = repr(exc)
            job.progress("failed")
            raise
        finally:
            job.finished_at = time.time()
            shutil.rmtree(job.directory, ignore_errors=True)
            with self._lock:
                self._jobs.pop(job.key, None)
                if self._active_by_user.get(job.user_id) is job:
                    self._active_by_user.pop(job.user_id, None)
                self._last_by_user[job.user_id] = job

    def status(self, user_id, active_only=False):
        with self._lock:
            job = self._active_by_user.get(str(user_id))
            if job is None and not active_only:
                job = self._last_by_user.get(str(user_id))
        return job.status() if job else None

    def is_stopping(self):
        with self._lock:
            return self._stopping

    def cancel_all(self):
        with self._lock:
            self._stopping = True
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()

    def shutdown(self, wait=False):
        self.cancel_all()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def reset_for_tests(self):
        with self._lock:
            self._stopping = False
            self._jobs.clear()
            self._active_by_user.clear()
            self._last_by_user.clear()


JOB_MANAGER = OcrJobManager()
