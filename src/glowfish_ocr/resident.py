from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .contracts import OcrHealth, OcrRequest, OcrResult, RegionOcrRequest
from .registry import normalize_engine, resolve_engine
from .validation import read_ocr_result, validate_ocr_input


SENTINEL = "@@OCR@@"


def _default_spawn(argv, **kwargs):
    kwargs.pop("purpose", None)
    kwargs.pop("job_id", None)
    return subprocess.Popen(argv, **kwargs)


def _default_terminate(process) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


class JsonLineOcrWorker:
    """Engine-neutral resident worker for the preserved JSON-lines protocol."""

    def __init__(
        self,
        argv_prefix,
        *,
        env=None,
        model_type="ocr",
        config=None,
        spawn=_default_spawn,
        terminate=_default_terminate,
        ready_timeout=120.0,
        result_timeout=3600.0,
    ):
        self.argv = list(argv_prefix) + ["--serve-worker"]
        if config:
            self.argv += ["--worker-config", json.dumps(config, ensure_ascii=False)]
        self.env = env
        self.model_type = model_type
        self._spawn = spawn
        self._terminate = terminate
        self._ready_timeout = ready_timeout
        self._result_timeout = result_timeout
        self._lock = threading.Lock()
        self._process = None
        self._events = queue.Queue()
        self._threads = []
        self._logger = logging.getLogger("glowfish.ocr.worker")

    @property
    def pid(self):
        return self._process.pid if self._process is not None else None

    def start(self):
        started = time.monotonic()
        self._process = self._spawn(
            self.argv,
            purpose="worker",
            job_id=None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._threads = [
            threading.Thread(target=self._pump_stdout, name="ocr-worker-stdout", daemon=True),
            threading.Thread(target=self._pump_stderr, name="ocr-worker-stderr", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        event = self._read_event(self._ready_timeout)
        if not (event and event.get("event") == "ready" and event.get("ok")):
            self.close()
            raise RuntimeError(f"worker not ready: {event}")
        self._logger.info("Worker ready pid=%s elapsed=%.3fs", self.pid, time.monotonic() - started)
        return self

    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _pump_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.rstrip("\n")
            if not line.startswith(SENTINEL):
                continue
            try:
                self._events.put(json.loads(line[len(SENTINEL):]))
            except Exception:
                self._events.put(None)

    def _pump_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._logger.error("pid=%s %s", process.pid, line.rstrip())

    def _read_event(self, timeout):
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"worker response timeout after {timeout}s") from exc

    def submit(self, images, out, progress=None, config=None, job_id=None):
        with self._lock:
            if not self.alive():
                raise RuntimeError("worker is not running")
            job = {
                "images": str(images),
                "out": str(out),
                "progress": str(progress) if progress else None,
                "config": config or {},
                "job_id": job_id,
            }
            self._process.stdin.write(json.dumps(job, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
            event = self._read_event(self._result_timeout)
            if not event or event.get("event") != "result":
                raise RuntimeError(f"worker protocol error: {event}")
            response_job_id = event.get("job_id")
            if response_job_id is not None and response_job_id != job_id:
                raise RuntimeError(f"worker response job mismatch: {response_job_id} != {job_id}")
            if not event.get("ok"):
                raise RuntimeError(f"worker OCR failed: {event.get('error')}")
            return event

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:
            pass
        self._terminate(process)


WorkerFactory = Callable[..., JsonLineOcrWorker]


class ResidentOcrService:
    """One-worker exact OCR service for hosts that own cross-engine fallback."""

    def __init__(
        self,
        legacy_dir: Path | None = None,
        paddle_python: Path | None = None,
        desktop_executable: Path | None = None,
        *,
        env=None,
        worker_factory: WorkerFactory = JsonLineOcrWorker,
        timer_factory=threading.Timer,
        idle_ttl_seconds=180.0,
        startup_attempts=2,
    ):
        self._legacy_dir = (
            Path(legacy_dir) if legacy_dir else Path(__file__).resolve().parent / "legacy"
        ).resolve()
        self._paddle_python = Path(paddle_python).resolve() if paddle_python else None
        self._desktop_executable = Path(desktop_executable).resolve() if desktop_executable else None
        self._env = env
        self._worker_factory = worker_factory
        self._timer_factory = timer_factory
        self._idle_ttl_seconds = float(idle_ttl_seconds)
        self._startup_attempts = max(1, int(startup_attempts))
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self._worker = None
        self._worker_engine = None
        self._worker_model_type = None
        self._worker_config_key = None
        self._idle_timer = None
        self._circuit_open = False

    def _resolve(self, engine, config=None):
        actual, prefix, defaults = resolve_engine(
            engine,
            self._legacy_dir,
            self._paddle_python,
            self._desktop_executable,
        )
        merged = {**defaults, **dict(config or {})}
        return actual, prefix, merged

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _close_worker(self) -> None:
        worker, self._worker = self._worker, None
        self._worker_engine = None
        self._worker_model_type = None
        self._worker_config_key = None
        if worker is not None:
            worker.close()

    def _worker_for(self, engine, prefix, config):
        model_type = config.get("model_type", engine)
        config_key = json.dumps(config, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._cancel_idle_timer()
            if (
                self._worker is not None
                and self._worker.alive()
                and self._worker_engine == engine
                and self._worker_model_type == model_type
                and self._worker_config_key == config_key
            ):
                return self._worker
            self._close_worker()
            if self._circuit_open:
                raise RuntimeError("resident OCR worker circuit is open")
            for _ in range(self._startup_attempts):
                worker = self._worker_factory(
                    prefix,
                    env=self._env,
                    model_type=model_type,
                    config=config,
                )
                try:
                    worker.start()
                    self._worker = worker
                    self._worker_engine = engine
                    self._worker_model_type = model_type
                    self._worker_config_key = config_key
                    return worker
                except Exception:
                    worker.close()
            self._circuit_open = True
            raise RuntimeError("resident OCR worker failed to start")

    def _schedule_idle_close(self, worker) -> None:
        if self._idle_ttl_seconds <= 0:
            return

        def close_if_idle():
            with self._lock:
                if self._worker is worker:
                    self._close_worker()
                self._idle_timer = None

        timer = self._timer_factory(self._idle_ttl_seconds, close_if_idle)
        if hasattr(timer, "daemon"):
            timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def recognize_exact(self, request: OcrRequest) -> OcrResult:
        with self._execution_lock:
            validate_ocr_input(request.image_dir, request.output_path, request.progress_path)
            actual, prefix, config = self._resolve(request.engine, request.config)
            worker = self._worker_for(actual, prefix, config)
            # A failed submission gets one clean resident rebuild. Startup failures
            # remain distinct so the host can apply its one-shot fallback policy.
            for attempt in range(2):
                try:
                    worker.submit(
                        request.image_dir,
                        request.output_path,
                        request.progress_path,
                        config,
                        job_id=request.job_id,
                    )
                    if not request.output_path.is_file():
                        raise RuntimeError("resident OCR worker produced no output")
                except Exception:
                    with self._lock:
                        if self._worker is worker:
                            self._close_worker()
                    if attempt == 0:
                        worker = self._worker_for(actual, prefix, config)
                        continue
                    raise
                with self._lock:
                    if self._worker is worker:
                        self._schedule_idle_close(worker)
                pages = read_ocr_result(request.output_path)
                return OcrResult(
                    request.engine, actual, pages, request.output_path
                )
            raise RuntimeError("resident OCR worker failed after rebuild")
    def recognize(self, request: OcrRequest) -> OcrResult:
        return self.recognize_exact(request)

    def recognize_region(self, request: RegionOcrRequest) -> OcrResult:
        return self.recognize_exact(request)

    def prewarm(self, engine: str) -> OcrHealth:
        with self._execution_lock:
            actual = normalize_engine(engine)
            try:
                actual, prefix, config = self._resolve(actual)
                self._worker_for(actual, prefix, config)
                return OcrHealth(True, actual)
            except Exception as exc:
                return OcrHealth(False, actual, type(exc).__name__)

    def shutdown(self) -> None:
        with self._execution_lock:
            with self._lock:
                self._cancel_idle_timer()
                self._close_worker()
